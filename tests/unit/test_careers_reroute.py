"""A careers page read in Chrome whose links lead to a known ATS board: that board goes to the
ATS plugin (JSON API fixtures, no network, no Chrome) instead of being read page by page."""

import asyncio
import json
from pathlib import Path

import httpx

from linkit_all.sources import registry
from linkit_all.sources.base import JobStub, Task
from linkit_all.sources.careers import Careers
from linkit_all.sources.http import Http

FIX = Path(__file__).parent.parent / "fixtures"
URL = "https://acme.test/careers"
SHELL = "<html><head><title>Careers</title></head><body></body></html>"  # JS-only listing


class FakeBrowser:
    """Stands in for BrowserExtractor: the stubs Chrome's page read produced."""

    def __init__(self, stubs: list[JobStub]) -> None:
        self.stubs = stubs

    async def jobs(self, http: Http, url: str) -> list[JobStub]:
        return self.stubs

    async def close(self) -> None:
        return None


def link(url: str, title: str = "Listing title", ats: str | None = None) -> JobStub:
    return JobStub(
        source="careers", url=url, title=title, company="Unknown", description="d", ats=ats
    )


def crawl(stubs: list[JobStub], failing: set[str] | None = None) -> list[JobStub]:
    """Careers search over a JS shell. ATS APIs answer with fixtures, 404 for hosts in `failing`."""
    gh = (FIX / "greenhouse" / "stripe_jobs.json").read_text("utf-8")
    lever = (FIX / "lever" / "palantir_postings.json").read_text("utf-8")

    def handler(req: httpx.Request) -> httpx.Response:
        host = req.url.host
        if host in (failing or set()):
            return httpx.Response(404)
        if host == "acme.test" and req.url.path == "/careers":
            return httpx.Response(200, text=SHELL)
        if host == "boards-api.greenhouse.io":
            return httpx.Response(200, text=gh)
        if host == "api.lever.co":
            return httpx.Response(200, text=lever)
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http = Http(client, default_rate=1000, attempts=1)
    plugins = {n: s for n, s in registry().items() if s.kind == "ats"}
    careers = Careers(plugins=plugins)
    careers._browser = FakeBrowser(stubs)  # type: ignore[assignment]

    async def go() -> list[JobStub]:
        async with client:
            task = Task("careers", f"careers:{URL}", board=URL)
            return [s async for page in careers.search(http, task, 0) for s in page]

    return asyncio.run(go())


def test_greenhouse_links_become_the_plugins_stubs() -> None:
    stubs = crawl(
        [
            link("https://boards.greenhouse.io/stripe/jobs/8172508", ats="greenhouse"),
            link("https://boards.greenhouse.io/stripe/jobs/1", ats="greenhouse"),
        ]
    )
    jobs = json.loads((FIX / "greenhouse" / "stripe_jobs.json").read_text("utf-8"))["jobs"]
    assert {s.source for s in stubs} == {"greenhouse"} and len(stubs) == len(jobs)
    assert all(s.description for s in stubs) and "Listing title" not in {s.title for s in stubs}
    assert jobs[0]["title"] in {s.title for s in stubs}


def test_lever_links_become_the_plugins_stubs() -> None:
    stubs = crawl([link("https://jobs.lever.co/palantir/6ed76ce8-4156", ats="lever")])
    assert stubs and {s.source for s in stubs} == {"lever"}
    assert all(s.description and s.title != "Listing title" for s in stubs)


def test_mixed_links_keep_the_non_ats_ones_generic() -> None:
    own = link("https://acme.test/jobs/9", "Own job")
    unknown = link("https://jobs.unknown-ats.example/acme/1", "Unknown ATS job")
    stubs = crawl([own, link("https://jobs.lever.co/palantir/x", ats="lever"), unknown])
    assert [s.title for s in stubs[:2]] == ["Own job", "Unknown ATS job"]  # as they were
    assert {s.source for s in stubs[:2]} == {"careers"}
    assert len(stubs) > 2 and {s.source for s in stubs[2:]} == {"lever"}


def test_unknown_ats_links_stay_generic() -> None:
    stubs = crawl([link("https://jobs.unknown-ats.example/acme/1", "Unknown ATS job")])
    assert [(s.source, s.title) for s in stubs] == [("careers", "Unknown ATS job")]


def test_a_failing_board_keeps_its_generic_stubs() -> None:
    stubs = crawl(
        [link("https://boards.greenhouse.io/stripe/jobs/1", "Kept", ats="greenhouse")],
        failing={"boards-api.greenhouse.io"},
    )
    assert [(s.source, s.title) for s in stubs] == [("careers", "Kept")]
