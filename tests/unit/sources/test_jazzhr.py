from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.jazzhr import JazzHR, job_links
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import posting_stub

URL = "https://proautomated.applytojob.com/apply/nfHu9c2Sxz/Field-Service-Engineer"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(
    load_fixture: Callable[[str], Any], detail_status: int = 200
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/apply":
            return httpx.Response(200, text=load_fixture("jazzhr/listing.html"))
        if req.url.path.startswith("/apply/nfHu9c2Sxz/"):
            if detail_status != 200:
                return httpx.Response(detail_status)
            return httpx.Response(200, text=load_fixture("jazzhr/detail.html"))
        return httpx.Response(404)

    return handler


def test_job_links(load_fixture: Callable[[str], Any]) -> None:
    links = job_links(load_fixture("jazzhr/listing.html"), "https://proautomated.applytojob.com/")
    assert links == [URL]  # the card links the job twice; /about is not a job


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(JazzHR(), _serve(load_fixture), board="proautomated")
    assert len(pages) == 1 and len(pages[0]) == 1
    job = pages[0][0]
    assert job.title == "Field Service Engineer" and job.company == "ProAutomated"
    assert job.url == URL and job.location == "Dover, DE" and job.description == "Fix machines."
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-06-16T00:00:00"
    assert job.extra["id"] == "nfHu9c2Sxz" and job.extra["board"] == "proautomated"
    assert job.ats == "jazzhr" and job.apply_url == URL


def test_a_posting_that_is_gone_is_skipped_and_other_errors_raise(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(JazzHR(), _serve(load_fixture, 404), board="proautomated") == [[]]
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(JazzHR(), _serve(load_fixture, 403), board="proautomated")


def test_posting_stub_edge_cases() -> None:
    def page(posting: str) -> str:
        return f'<script type="application/ld+json">{posting}</script>'

    kw: dict[str, Any] = {"source": "x", "url": "u", "board": "b", "id": "1", "company": "Fallback"}
    assert posting_stub("<html></html>", **kw) is None
    assert posting_stub(page('{"@type":"JobPosting","title":""}'), **kw) is None
    bad = page(
        '{"@type":"JobPosting","title":"T","datePosted":"soon","baseSalary":{"value":{"minValue":""}}}'
    )
    stub = posting_stub(bad, **kw)
    assert stub is not None and stub.posted_at is None and stub.company == "Fallback"
    assert stub.salary_min is None


def test_url_patterns() -> None:
    assert detect(URL) == ("jazzhr", "proautomated")
    assert detect("jazzhr:proautomated") == ("jazzhr", "proautomated")
