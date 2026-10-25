from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.alignerr import Alignerr


def handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    files = {
        "/jobs": "jobs.html",
        "/jobs/aaa": "job_aaa.html",
        "/jobs/gone": "job_gone.html",
        "/jobs/live2": "job_live2.html",
    }

    def handle(req: httpx.Request) -> httpx.Response:
        name = files.get(req.url.path)
        if req.url.path == "/robots.txt" or not name:
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture(f"alignerr/{name}"))

    return handle


def test_listing_then_details(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Alignerr(), handler(load_fixture))
    assert len(pages) == 1
    first, second = pages[0]
    assert first.title == "Software Engineer Task Author (AI Training)"
    assert first.company == "Alignerr" and first.url == "https://www.alignerr.com/jobs/aaa"
    assert first.location == "Remote" and first.remote == "remote"  # the listing's location
    assert "Build tasks." in first.description and "alert" not in first.description
    assert first.posted_at is not None and first.posted_at.isoformat().startswith("2026-07-07")
    assert first.extra == {"id": "aaa"} and first.source == "alignerr"
    # no listed location: the posting's own; no long description: the short one
    assert second.location == "United States" and second.description == "Short\ntext"


def test_resume_and_missing_detail(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(Alignerr(), handler(load_fixture), start_page=1) == []
    broken = lambda req: httpx.Response(404)  # noqa: E731
    assert search_pages(Alignerr(), broken) == []  # no listing page: nothing, not a crash


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="alignerr", url="https://www.alignerr.com/jobs/aaa", title="t", company="Alignerr"
    )
    assert "Build tasks." in fetch_details(Alignerr(), handler(load_fixture), stub).description
