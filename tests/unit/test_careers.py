import asyncio
import re
from pathlib import Path

import httpx
import pytest

from linkit_all.core.db import init_db
from linkit_all.core.runs import current_run
from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.base import JobStub, Task
from linkit_all.sources.careers import Careers, Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.runner import company_tasks, discover

FIX = Path(__file__).parent.parent / "fixtures" / "careers"
LISTING = "https://www.mozilla.org/en-US/careers/listings/"
JOB = FIX / "mozilla_job.html"


def site(
    pages: dict[str, str], robots: str | None = None, calls: list[str] | None = None
) -> tuple[httpx.AsyncClient, list[str]]:
    """A fake website: path -> HTML. `robots` None = no robots.txt (404)."""
    seen = calls if calls is not None else []

    def handler(req: httpx.Request) -> httpx.Response:
        key = req.url.path + (f"?{req.url.query.decode()}" if req.url.query else "")
        seen.append(key)
        if key == "/robots.txt":
            return httpx.Response(404) if robots is None else httpx.Response(200, text=robots)
        if key in pages:
            return httpx.Response(200, text=pages[key])
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), seen


def run_search(
    client: httpx.AsyncClient,
    url: str,
    limit: int = 200,
    known: tuple[str, ...] = (),
) -> tuple[list[JobStub], Http]:
    http = Http(client, default_rate=1000, attempts=1)

    async def go() -> list[JobStub]:
        async with client:
            task = Task("careers", f"careers:{url}", board=url, limit=limit)
            careers = Careers()
            careers.seen_url = known.__contains__
            return [s async for page in careers.search(http, task, 0) for s in page]

    return asyncio.run(go()), http


def listing_with_jobs() -> tuple[dict[str, str], list[str]]:
    """The saved Mozilla listing, with job pages served for exactly the links it contains."""
    listing = (FIX / "mozilla_listings.html").read_text("utf-8")
    paths = re.findall(r'href="(/en-US/careers/position/gh/\d+/)"', listing)
    job = JOB.read_text("utf-8")
    return {"/en-US/careers/listings/": listing, **dict.fromkeys(paths, job)}, paths


def test_jsonld_on_the_careers_page() -> None:
    html = (FIX / "lever_job_jsonld.html").read_text("utf-8")
    client, calls = site({"/careers": html})
    stubs, _ = run_search(client, "https://careers.acme.test/careers")
    assert calls == ["/robots.txt", "/careers"]  # no job links followed
    assert [s.title for s in stubs] == ["Administrative Business Partner"]
    stub = stubs[0]
    assert stub.company == "Palantir Technologies" and stub.source == "careers"
    assert "Singapore" in stub.location and stub.posted_at is not None
    assert stub.url == "https://careers.acme.test/careers"


def test_link_heuristics_without_a_provider() -> None:
    pages, paths = listing_with_jobs()
    client, calls = site(pages)
    stubs, _ = run_search(client, LISTING)
    assert len(paths) == 6 and len(stubs) == 6
    # robots.txt, the listing, then only the 6 job pages: nav links (benefits, home) skipped
    assert calls == ["/robots.txt", "/en-US/careers/listings/", *paths]
    first = stubs[0]
    assert first.title == "Staff Data Scientist, Ads"  # from the page's h1
    assert first.company == "Mozilla" and first.url == f"https://www.mozilla.org{paths[0]}"
    assert "Hiring Ranges" in first.description
    client2, _ = site(pages)
    assert len(run_search(client2, LISTING, limit=3)[0]) == 3


def no_location(html: str) -> str:
    return html.replace("Locations:", "").replace(
        '<dd class="job-post-location">Remote US</dd>', ""
    )


def bare_site(n: int, job_html: str = "") -> dict[str, str]:
    """A listing with n job links; each job page has an h1 but, by default, no location."""
    links = "".join(f'<a href="/jobs/role-{i}-x">Backend Engineer {i}</a>' for i in range(n))
    default = "<html><body><h1>Role {i}</h1><p>Build things. Hiring now.</p></body></html>"
    pages = {"/careers": f"<html><body><p>{'Open roles. ' * 30}</p>{links}</body></html>"}
    for i in range(n):
        pages[f"/jobs/role-{i}-x"] = (job_html or default).replace("{i}", str(i))
    return pages


CAREERS = "https://acme.test/careers"


def test_pages_are_read_without_ai() -> None:
    labelled = (
        "<html><body><h1>Role {i}</h1><p>Location: Cairo, Egypt</p><p>Build.</p></body></html>"
    )
    meta = '<html><head><meta name="geo.placename" content="Berlin"></head><body><h1>R {i}</h1></body></html>'
    for html, where in ((labelled, "Cairo, Egypt"), (meta, "Berlin")):
        client, _ = site(bare_site(12, html))
        stubs, _ = run_search(client, CAREERS)
        assert len(stubs) == 12 and stubs[0].location == where
    client, _ = site(bare_site(3))  # no location anywhere: heading and text are enough
    stubs, _ = run_search(client, CAREERS)
    assert [s.title for s in stubs] == ["Role 0", "Role 1", "Role 2"]
    assert all(s.location == "" and "Build things" in s.description for s in stubs)
    pages, _ = listing_with_jobs()  # Mozilla's "Locations:" label + value on the next line
    client, _ = site(pages)
    assert run_search(client, LISTING)[0][0].location == "Remote US"


def test_a_stored_job_page_is_not_read_again() -> None:
    client, calls = site(bare_site(2))
    known = ("https://acme.test/jobs/role-0-x",)
    stubs, _ = run_search(client, CAREERS, known=known)
    assert "/jobs/role-0-x" not in calls and "/jobs/role-1-x" in calls
    assert sorted(s.url for s in stubs) == [known[0], "https://acme.test/jobs/role-1-x"]


def test_next_page_is_followed_and_capped() -> None:
    def page(n: int) -> str:
        body = "Open roles at Acme. " * 20
        jobs = (
            f'<a href="/jobs/role-{n}-a">Backend Engineer {n}</a><a href="/jobs/role-{n}-b">Go</a>'
        )
        return f'<html><body><p>{body}</p>{jobs}<a rel="next" href="/list?p={n + 1}">Next</a></body></html>'

    pages = {"/list": page(1), **{f"/list?p={n}": page(n) for n in range(2, 9)}}
    client, calls = site(pages)
    run_search(client, "https://acme.test/list")
    lists = [c for c in calls if c.startswith("/list")]
    assert lists == ["/list", "/list?p=2", "/list?p=3", "/list?p=4"]  # MAX_LIST_PAGES


def test_robots_disallow_is_not_enforced() -> None:
    pages, paths = listing_with_jobs()
    client, calls = site(pages, robots="User-agent: *\nDisallow: /\n")
    stubs, _ = run_search(client, LISTING)
    assert len(stubs) == 6 and calls == ["/robots.txt", "/en-US/careers/listings/", *paths]


def test_crawl_delay_lowers_the_host_rate() -> None:
    html = (FIX / "lever_job_jsonld.html").read_text("utf-8")
    client, _ = site({"/careers": html}, robots="User-agent: *\nCrawl-delay: 5\n")
    _, http = run_search(client, "https://careers.acme.test/careers")
    assert http._rates["careers.acme.test"] == pytest.approx(0.2)


def test_js_rendered_page_is_unsupported() -> None:
    html = '<html><head><title>Careers</title></head><body><div id="root"></div></body></html>'
    client, calls = site({"/careers": html})
    with pytest.raises(Unsupported, match="needs a browser; not supported yet"):
        run_search(client, "https://acme.test/careers")
    assert calls == ["/robots.txt", "/careers"]


def test_bot_challenge_is_unsupported() -> None:
    html = "<html><head><title>Just a moment...</title></head><body>Checking</body></html>"
    client, _ = site({"/careers": html})
    with pytest.raises(Unsupported, match="bot challenge"):
        run_search(client, "https://acme.test/careers")


def test_unknown_careers_url_is_routed_here_and_unsupported_is_reported(tmp_path: Path) -> None:
    html = '<html><head><title>Careers</title></head><body><div id="root"></div></body></html>'
    client, _ = site({"/careers": html})
    cfg = SearchConfig.model_validate(
        {"sources": {"companies": ["https://acme.test/careers", "ftp-not-a-url"]}}
    )

    async def go() -> object:
        async with client:
            http = Http(client, default_rate=1000, attempts=1)
            tasks, unsupported = await company_tasks(cfg, http, registry())
            assert [t.key for t in tasks] == ["careers:https://acme.test/careers"]
            assert len(unsupported) == 1 and "ftp-not-a-url" in unsupported[0]
            db = init_db(tmp_path / "t.db")
            return await discover(db, cfg, current_run(db), http, registry())

    stats = asyncio.run(go())
    assert any("needs a browser" in u for u in stats.unsupported)  # type: ignore[attr-defined]
    assert not stats.errors  # type: ignore[attr-defined]
