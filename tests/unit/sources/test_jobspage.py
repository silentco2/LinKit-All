from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.jobspage import JobsPage
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))
    yield


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/":
            return httpx.Response(200, text=load_fixture("jobspage/listing.html"))
        if path == "/ab12cd34-backend-developer":
            return httpx.Response(200, text=load_fixture("jobspage/detail.html"))
        if path == "/fl000000-flaky-role":
            return httpx.Response(503)
        raise httpx.TooManyRedirects("redirect loop to /404", request=req)  # "no such page"

    return handler


def test_listing_then_posting_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(JobsPage(), make_handler(load_fixture), board="acme")
    assert len(pages) == 1
    # The expired posting is skipped, the gone one (redirect loop) is dropped, the flaky one stays.
    assert [j.title for j in pages[0]] == ["Backend Developer", "Flaky Role"]
    a, flaky = pages[0]
    assert a.url == "https://acme.jobspage.co/ab12cd34-backend-developer"
    assert a.company == "Acme Ltd" and a.location == "Limassol, CY" and a.remote == "remote"
    assert a.description == "Own the backend."  # the JobPosting body, not the Draft.js one
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-01T10:23:34"
    assert a.extra == {
        "board": "acme",
        "id": "ab12cd34-backend-developer",
        "employment": "Full-time",
    }
    assert flaky.description == "" and flaky.remote is None  # "Remote friendly" is not a mode


def test_resume_skips_earlier_chunks(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(JobsPage(), make_handler(load_fixture), board="acme", start_page=1) == []


def test_unknown_board_is_an_error(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.TooManyRedirects("redirect loop to /404", request=req)

    with pytest.raises(ValueError, match="no career site"):
        search_pages(JobsPage(), handler, board="nobody")


def test_page_without_jobs_data_is_an_error(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<html><body>reshaped</body></html>")

    with pytest.raises(ValueError, match="jobsData"):
        search_pages(JobsPage(), handler, board="acme")


def test_fetch_details_reads_the_posting_page(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="jobspage",
        url="https://acme.jobspage.co/ab12cd34-backend-developer",
        title="t",
        company="c",
    )
    full = fetch_details(JobsPage(), make_handler(load_fixture), stub)
    assert full.description == "Own the backend." and full.posted_at is not None


def test_url_patterns() -> None:
    assert detect("https://acme.jobspage.co/ab12cd34-backend-developer") == ("jobspage", "acme")
    assert detect("jobspage:acme") == ("jobspage", "acme")
    assert detect("https://www.jobspage.co/pricing") is None
