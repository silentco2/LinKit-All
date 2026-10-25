from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.icims import Icims, host_of
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(routes: dict[str, str]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        for key in sorted(routes, key=len, reverse=True):
            if str(req.url).endswith(key):
                return httpx.Response(200, text=routes[key])
        return httpx.Response(404)

    return handler


def test_host_of() -> None:
    assert host_of("360care") == "careers-360care.icims.com"
    assert host_of("careers.docusign.com") == "careers.docusign.com"


def test_classic_board(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    routes = {
        "/sitemap.xml": load_fixture("icims/sitemap.xml"),
        "/jobs/555/mobile-medical-assistant/job?in_iframe=1": load_fixture("icims/detail.html"),
    }
    pages = search_pages(Icims(), _serve(routes), board="360care", calls=calls)
    assert len(pages) == 1 and len(pages[0]) == 1  # /jobs/search and /jobs/intro are not postings
    job = pages[0][0]
    assert job.title == "Mobile Medical Assistant" and job.company == "360care Inc"
    assert job.url == "https://careers-360care.icims.com/jobs/555/mobile-medical-assistant/job"
    assert job.location == "Kalamazoo, MI, US"  # the UNAVAILABLE placeholders are dropped
    assert job.description == "Overview\nAssist physicians."
    assert job.posted_at is not None and (job.posted_at.year, job.posted_at.month) == (2026, 4)
    assert job.extra == {"employment": None, "valid_through": None, "board": "360care", "id": "555"}
    assert job.ats == "icims"
    assert calls[-1].endswith("?in_iframe=1")


def test_vanity_board_follows_the_sitemap_index_and_uses_the_careers_home_fragment(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    routes = {
        "/sitemap.xml": load_fixture("icims/index.xml"),
        "/sitemap1.xml": load_fixture("icims/sub.xml"),
        "/careers-home/jobs/27897?in_iframe=1": load_fixture("icims/detail_single.html"),
    }
    pages = search_pages(Icims(), _serve(routes), board="careers.docusign.com", calls=calls)
    jobs = [j for p in pages for j in p]
    assert len(jobs) == 1  # the same job in two languages is one posting
    job = jobs[0]
    assert job.url == "https://careers.docusign.com/jobs/27897?lang=en-us"
    assert job.location == "Seattle, Washington, US" and job.remote == "remote"
    assert job.company == "Acme" and job.extra["id"] == "27897"
    assert "https://careers.docusign.com/careers-home/jobs/27897?in_iframe=1" in calls


def test_missing_fragment_is_skipped_and_paging_resumes(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from linkit_all.sources import common

    monkeypatch.setattr(common, "PAGE", 1)
    locs = "".join(
        f"<url><loc>https://careers-a.icims.com/jobs/{i}/x/job</loc></url>" for i in (1, 2)
    )
    routes = {
        "/sitemap.xml": f"<urlset>{locs}</urlset>",
        "/jobs/2/x/job?in_iframe=1": load_fixture("icims/detail.html"),
    }
    pages = search_pages(Icims(), _serve(routes), board="a")
    assert [[s.extra["id"] for s in p] for p in pages] == [[], ["2"]]  # job 1's fragment is a 404
    pages = search_pages(Icims(), _serve(routes), board="a", start_page=1)
    assert [[s.extra["id"] for s in p] for p in pages] == [["2"]]


def test_url_patterns() -> None:
    assert detect("https://careers-360care.icims.com/jobs/555/x/job") == ("icims", "360care")
    assert detect("icims:careers.docusign.com") == ("icims", "careers.docusign.com")
