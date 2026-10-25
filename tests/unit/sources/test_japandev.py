from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.base import JobStub
from linkit_all.sources.boards.japandev import JapanDev, nuxt_job, posting_slug
from linkit_all.sources.http import Http

PLAIN = "https://japan-dev.com/jobs/abbeal/abbeal-ai-engineer-maj4uw"
PAY = "https://japan-dev.com/jobs/abbeal/abbeal-ai-engineer-pay-zz9"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    pages = {
        "/sitemap.xml": "japandev/sitemap.xml",
        "/cdn/sitemaps/sitemap.xml": "japandev/sitemap-jobs.xml",
        "/jobs/abbeal/abbeal-ai-engineer-maj4uw": "japandev/detail.html",
        "/jobs/abbeal/abbeal-ai-engineer-pay-zz9": "japandev/detail_pay.html",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        name = pages.get(req.url.path)
        return httpx.Response(200, text=load_fixture(name)) if name else httpx.Response(404)

    return handler


def test_posting_slug() -> None:
    assert posting_slug(PLAIN) == "abbeal-ai-engineer-maj4uw"
    others = (
        "https://japan-dev.com/",
        "https://japan-dev.com/jobs",
        "http://japan-dev.com/jobs/a/b",
        "https://example.com/jobs/a/b",
        "https://japan-dev.com/jobs/a/b/c",
    )
    assert all(posting_slug(other) == "" for other in others)


def test_nuxt_job(load_fixture: Callable[[str], Any]) -> None:
    job = nuxt_job(load_fixture("japandev/detail_pay.html"))
    assert job is not None
    assert job["company"] == "Abbeal" and job["salary_min"] == 7000000
    assert job["skills"] == ["Engineering", "Eng - Other"]
    assert nuxt_job("<html></html>") is None
    assert nuxt_job('<script id="__NUXT_DATA__">not json</script>') is None


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(JapanDev(), _serve(load_fixture), calls=calls)
    by_url = {s.url: s for p in pages for s in p}
    assert set(by_url) == {PLAIN, PAY}  # the gone posting is dropped, other pages never fetched
    assert not any(c.endswith(("/blog", "/jobs", "japan-dev.com/")) for c in calls)
    job = by_url[PLAIN]
    assert job.title == "AI Engineer" and job.company == "Abbeal" and job.location == "Tokyo"
    assert job.remote == "hybrid" and job.apply_url == PLAIN and job.ats == "japandev"
    assert job.salary_min is None and job.salary_currency is None
    assert job.description.startswith("Applications: candidates must already be in Japan")
    assert "Visa sponsorship: not available" in job.description
    assert "English: Business level" in job.description
    assert "Japanese: Not required" in job.description
    assert "Japan Dev tags: Engineering, Eng - Other" in job.description
    assert "Location requirement" in job.description and "<" not in job.description
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-09-07"
    assert job.extra["id"] == "abbeal-ai-engineer-maj4uw"


def test_pay_and_apply_link(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(JapanDev(), _serve(load_fixture))
    job = next(s for p in pages for s in p if s.url == PAY)
    assert (job.salary_min, job.salary_max) == (7000000, 10000000)
    assert (job.salary_currency, job.salary_interval) == ("JPY", "year")
    assert job.remote == "remote" and job.ats == "greenhouse"
    assert job.apply_url == "https://boards.greenhouse.io/abbeal/jobs/12345"
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-10-01"


def test_slug_mismatch_is_dropped(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    base = _serve(load_fixture)

    def handler(req: httpx.Request) -> httpx.Response:  # every page claims to be the plain one
        if req.url.path.startswith("/jobs/"):
            return httpx.Response(200, text=load_fixture("japandev/detail.html"))
        return base(req)

    stubs = [s for p in search_pages(JapanDev(), handler) for s in p]
    assert [s.url for s in stubs] == [PLAIN]
