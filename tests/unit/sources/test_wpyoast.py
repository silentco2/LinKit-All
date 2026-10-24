from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.wpyoast import WPYoast
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def handler_for(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/sitemap.xml":
            return httpx.Response(200, text=load_fixture("wpyoast/sitemap_index.xml"))
        if path == "/job_listing-sitemap.xml":
            return httpx.Response(200, text=load_fixture("wpyoast/job_listing_sitemap.xml"))
        if path == "/job/640127-electrical-engineer-corona-california/":
            return httpx.Response(200, text=load_fixture("wpyoast/job.html"))
        return httpx.Response(404)  # robots.txt, and the job that has since been removed

    return handler


def test_index_to_job_sitemap_to_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        WPYoast(), handler_for(load_fixture), board="careers.acme.com", calls=calls
    )
    assert "https://careers.acme.com/job_listing-sitemap.xml" in calls
    assert not any(c.endswith("/jobs/") for c in calls)  # no numeric id: not a job
    assert len(pages) == 1 and len(pages[0]) == 1  # the removed job (404) is skipped
    job = pages[0][0]
    assert job.title == "Electrical Engineer III – Design"  # noqa: RUF001 - entity-decoded
    assert job.company == "Acme Group" and job.location == "Corona, CA, US"
    assert job.url == "https://careers.acme.com/job/640127-electrical-engineer-corona-california/"
    assert job.description == "Design things."  # script dropped
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-05-19"
    assert job.ats == "wpyoast" and (job.extra["board"], job.extra["id"]) == (
        "careers.acme.com",
        "640127",
    )


def test_no_job_sitemap_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    index = "<sitemapindex><sitemap><loc>https://careers.acme.com/page-sitemap.xml</loc></sitemap></sitemapindex>"
    handler = lambda req: httpx.Response(200, text=index)  # noqa: E731
    assert search_pages(WPYoast(), handler, board="careers.acme.com") == []
    assert (
        search_pages(WPYoast(), handler_for(load_fixture), board="careers.acme.com", start_page=1)
        == []
    )


def test_board_is_named_not_detected() -> None:
    assert detect("wpyoast:careers.acme.com") == ("wpyoast", "careers.acme.com")
