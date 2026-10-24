from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.trakstar import Trakstar
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def serving(xml: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda req: (
        httpx.Response(404)
        if req.url.path == "/robots.txt"
        else httpx.Response(200, content=xml.encode())
    )


def test_rss_feed_maps_items(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Trakstar(), serving(load_fixture("trakstar/feed.xml")), board="cheesecakelabs", calls=calls
    )
    assert "https://cheesecakelabs.hire.trakstar.com/jobfeeds/cheesecakelabs" in calls
    assert len(pages) == 1 and len(pages[0]) == 2
    a, b = pages[0]
    assert a.title == "Senior Go Engineer" and a.company == "Cheesecake Labs"
    assert a.url == "https://cheesecakelabs.hire.trakstar.com/jobs/fk0zjzb"  # http -> https
    assert a.extra["id"] == "fk0zjzb" and a.ats == "trakstar"
    assert a.location == "Florianópolis, SC, Brazil" and a.remote is None
    assert "pipeline" in a.description and "<" not in a.description  # entity-unescaped
    assert "x()" not in a.description  # script dropped
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-06-17T18:30:00"
    assert b.remote == "remote" and b.location == "Remote, Brazil"  # empty state skipped


def test_empty_feed_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = serving(load_fixture("trakstar/empty.xml"))
    assert search_pages(Trakstar(), handler, board="way2") == [[]]
    assert search_pages(Trakstar(), handler, board="way2", start_page=1) == []


def test_url_patterns() -> None:
    assert detect("https://cheesecakelabs.hire.trakstar.com/jobs/fk0zjzb") == (
        "trakstar",
        "cheesecakelabs",
    )
    assert detect("trakstar:acme") == ("trakstar", "acme")
