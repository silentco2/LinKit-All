from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.base import JobStub
from linkit_all.sources.boards.jobylon import Jobylon
from linkit_all.sources.http import Http

HEMA = "https://emp.jobylon.com/jobs/313390-hema-employe-de-vente-hf/"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any], detail: str = "") -> Callable[..., httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text=load_fixture("jobylon/sitemap.xml"))
        if req.url.path == "/sitemap-jobs.xml":
            return httpx.Response(200, text=load_fixture("jobylon/sitemap-jobs.xml"))
        if req.url.path.startswith("/jobs/313390"):
            return httpx.Response(200, text=detail or load_fixture("jobylon/detail.html"))
        return httpx.Response(404)

    return handler


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Jobylon(), _serve(load_fixture), query="x", calls=calls)
    stubs = [s for p in pages for s in p]
    assert [s.url for s in stubs] == [HEMA]  # the company page is skipped, the gone job dropped
    assert not any("/companies/" in c for c in calls)
    job = stubs[0]
    assert job.company == "HEMA"
    assert "Employ" in job.title and job.title.endswith("H/F")
    assert "Paris" in job.location and "France" in job.location
    assert "&#39;" not in job.description and "<h2" not in job.description
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-07-30"
    assert job.extra["id"] == "313390" and job.ats == "jobylon"


def test_posting_without_company_is_dropped(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    page = load_fixture("jobylon/detail.html").replace('"name": "HEMA"', '"name": ""')
    assert [s for p in search_pages(Jobylon(), _serve(load_fixture, page)) for s in p] == []


def test_missing_job_sitemap_is_an_error(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    empty = "<sitemapindex><sitemap><loc>https://emp.jobylon.com/other.xml</loc></sitemap></sitemapindex>"
    with pytest.raises(ValueError, match="sitemap-jobs"):
        search_pages(Jobylon(), lambda req: httpx.Response(200, text=empty))
