from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.teamtailor import Teamtailor
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http

HOST = "jobs.acme.com"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(
    load_fixture: Callable[[str], Any], *, listing: str = "/jobs", feed: bool = True
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == listing:  # page 1 lists the postings, every later page is empty
            page = req.url.params["page"]
            return httpx.Response(
                200,
                text=load_fixture("teamtailor/listing.html") if page == "1" else "<html></html>",
            )
        if path == "/jobs.rss" and feed:
            return httpx.Response(200, text=load_fixture("teamtailor/jobs.rss"))
        if path in ("/jobs/12345-cloud-engineer", "/jobs/678901-designer"):
            return httpx.Response(200, text=load_fixture("teamtailor/detail.html"))
        return httpx.Response(404)  # robots.txt, /jobs/555555-gone, a missing feed

    return handler


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Teamtailor(), _serve(load_fixture), board=HOST)
    assert len(pages) == 1
    cloud, designer = pages[0]  # the repeated link counts once; /jobs/555555-gone is a 404
    assert cloud.title == "Cloud Engineer" and cloud.company == "Acme AB"
    assert cloud.url == "https://jobs.acme.com/jobs/12345-cloud-engineer"
    assert cloud.location == "Stockholm, SE" and cloud.ats == "teamtailor"
    assert "Run" in cloud.description and "alert" not in cloud.description
    assert cloud.posted_at is not None and cloud.posted_at.isoformat() == "2026-07-20T08:00:00"
    assert cloud.extra["board"] == HOST and cloud.extra["id"] == "12345"
    assert cloud.remote == "hybrid"  # from the feed's remoteStatus
    assert designer.url == "https://jobs.acme.com/jobs/678901-designer"
    assert designer.remote is None  # remoteStatus "none" states nothing


def test_without_the_feed_the_pages_stand_alone(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Teamtailor(), _serve(load_fixture, feed=False), board=HOST)
    assert [s.remote for s in pages[0]] == [None, None]


def test_a_site_without_a_jobs_page_lists_on_its_root(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Teamtailor(), _serve(load_fixture, listing="/"), board=HOST)
    assert [s.extra["id"] for s in pages[0]] == ["12345", "678901"]


def test_resume_past_the_end_yields_nothing(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(Teamtailor(), _serve(load_fixture), board=HOST, start_page=1) == []


def test_a_server_error_raises(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(Teamtailor(), lambda req: httpx.Response(403), board=HOST)


def test_url_patterns() -> None:
    assert detect("https://acme.teamtailor.com/jobs/12345-cloud-engineer") == (
        "teamtailor",
        "acme.teamtailor.com",
    )
    assert detect("https://jobs.acme.com/jobs/12345-cloud-engineer") == ("teamtailor", HOST)
    assert detect("https://jobs.acme.com/jobs/connect") is None
    assert detect(f"teamtailor:{HOST}") == ("teamtailor", HOST)
