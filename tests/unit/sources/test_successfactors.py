from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.successfactors import SuccessFactors
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/job_sitemap.xml":
            return httpx.Response(200, text=load_fixture("successfactors/sitemap.xml"))
        if req.url.path.startswith("/job/Munich") or req.url.path.startswith("/job/Lund"):
            return httpx.Response(200, text=load_fixture("successfactors/detail.html"))
        return httpx.Response(404)

    return handler


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(SuccessFactors(), _serve(load_fixture), board="jobs.tetrapak.com")
    assert len(pages) == 1 and len(pages[0]) == 2  # /search/ has no id and Gone-Role is a 404
    munich, lund = pages[0]
    assert munich.title == "Commissioning Engineer" and munich.company == "Tetrapak"
    assert munich.url == "https://jobs.tetrapak.com/job/Munich-Commissioning-Engineer/12345/"
    assert "Build it." in munich.description and "alert" not in munich.description
    assert munich.posted_at is not None and munich.posted_at.date().isoformat() == "2026-06-06"
    assert (
        munich.extra == {"board": "jobs.tetrapak.com", "id": "12345"}
        and munich.ats == "successfactors"
    )
    assert lund.extra["id"] == "98012" and lund.posted_at is None  # the locale suffix is not the id


def test_a_page_that_is_not_a_posting_is_skipped(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/job_sitemap.xml":
            return httpx.Response(200, text=load_fixture("successfactors/sitemap.xml"))
        return httpx.Response(200, text="<html><body>Search</body></html>")

    assert search_pages(SuccessFactors(), handler, board="jobs.tetrapak.com") == [[]]


def test_title_falls_back_to_og_title(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    page = '<head><meta property="og:title" content="From Meta"></head><div itemprop="description">x</div>'

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/job_sitemap.xml":
            return httpx.Response(200, text=load_fixture("successfactors/sitemap.xml"))
        return httpx.Response(200, text=page)

    stubs = search_pages(SuccessFactors(), handler, board="jobs.tetrapak.com")[0]
    assert {s.title for s in stubs} == {"From Meta"}


def test_url_patterns() -> None:
    url = "https://jobs.tetrapak.com/job/Lund-Process-Engineer/98012-en_GB"
    assert detect(url) == ("successfactors", "jobs.tetrapak.com")
    assert detect("successfactors:jobs.tetrapak.com") == ("successfactors", "jobs.tetrapak.com")
