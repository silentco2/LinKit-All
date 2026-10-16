import asyncio
import json
import re
from pathlib import Path

import httpx
import pytest

from linkit_all.core.db import init_db
from linkit_all.core.runs import current_run
from linkit_all.core.search import SearchConfig
from linkit_all.providers.base import LLMProvider
from linkit_all.sources import registry
from linkit_all.sources.base import JobStub, Task
from linkit_all.sources.careers import Careers, Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.runner import company_tasks, discover

FIX = Path(__file__).parent.parent / "fixtures" / "careers"
LISTING = "https://www.mozilla.org/en-US/careers/listings/"
JOB = FIX / "mozilla_job.html"


class FakeAI(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        super().__init__("fake")
        self.prompts: list[str] = []

    async def _call(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return json.dumps(
            {
                "title": "Staff Data Scientist (Ads)",
                "location": "Remote US",
                "remote": "remote",
                "employment_type": "Full-time",
                "posted_date": "2026-09-01",
            }
        )


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
    provider: LLMProvider | None = None,
    limit: int = 200,
) -> tuple[list[JobStub], Http]:
    http = Http(client, default_rate=1000, attempts=1)

    async def go() -> list[JobStub]:
        async with client:
            task = Task("careers", f"careers:{url}", board=url, limit=limit)
            return [s async for page in Careers(provider).search(http, task, 0) for s in page]

    return asyncio.run(go()), http


def mozilla_pages() -> dict[str, str]:
    listing = (FIX / "mozilla_listings.html").read_text("utf-8")
    pages = {"/en-US/careers/listings/": listing}
    for job_id in range(1, 100):  # every job link serves the saved job page
        pages[f"/en-US/careers/position/gh/{job_id}/"] = JOB.read_text("utf-8")
    return pages


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


def test_ai_extraction_decides_fields_not_urls() -> None:
    pages, paths = listing_with_jobs()
    client, _ = site(pages)
    ai = FakeAI()
    stubs, _ = run_search(client, LISTING, ai, limit=2)
    assert len(ai.prompts) == 2 and "Hiring Ranges" in ai.prompts[0]
    assert "job-boards.greenhouse.io" not in ai.prompts[0]  # page text only, no hrefs
    s = stubs[0]
    assert (s.title, s.location, s.remote) == ("Staff Data Scientist (Ads)", "Remote US", "remote")
    assert s.posted_at is not None and s.posted_at.year == 2026
    assert s.url == f"https://www.mozilla.org{paths[0]}"  # the URL is always ours
    assert s.extra["employment"] == "Full-time"


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


def test_robots_disallow_fetches_nothing_else() -> None:
    client, calls = site(mozilla_pages(), robots="User-agent: *\nDisallow: /\n")
    with pytest.raises(Unsupported, match=r"robots\.txt"):
        run_search(client, LISTING)
    assert calls == ["/robots.txt"]


def test_robots_group_for_our_token_and_server_errors() -> None:
    robots = "User-agent: *\nAllow: /\n\nUser-agent: LinKitAll\nDisallow: /en-US/careers/\n"
    client, calls = site(mozilla_pages(), robots=robots)
    with pytest.raises(Unsupported):
        run_search(client, LISTING)
    assert calls == ["/robots.txt"]

    def boom(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    http = Http(httpx.AsyncClient(transport=httpx.MockTransport(boom)), attempts=1)
    assert asyncio.run(http.allowed("https://acme.test/jobs")) is False  # 5xx = do not crawl
    assert asyncio.run(Http(site({})[0]).allowed("https://acme.test/jobs")) is True  # 404 = allow


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
