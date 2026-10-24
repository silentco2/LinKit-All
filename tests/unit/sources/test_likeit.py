from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.likeit import Likeit
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def handler_for(xml: str) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, content=xml.encode())

    return handler


def test_rss_feed(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Likeit(), handler_for(load_fixture("likeit/rss.xml")), board="rekrymesta", calls=calls
    )
    assert "https://rekrymesta.likeit.fi/jsp/duuni/AdvertRss.jsp" in calls
    assert len(pages) == 1 and len(pages[0]) == 2  # the channel's list link has no advert id
    a, b = pages[0]
    assert a.title == "Lähihoitaja, Helsinki"  # trimmed
    assert a.url == "https://rekrymesta.likeit.fi/jsp/duuni/AdvertShow.jsp?guest=1&id=4711"
    assert a.extra == {"board": "rekrymesta", "id": "4711"}  # read from the query, any order
    assert a.company == "Rekrymesta" and a.location == "Uusimaa, Helsinki" and a.ats == "likeit"
    assert a.description == "Etsimme lähihoitajaa."
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-05T05:00:00"  # dc:date
    assert b.remote == "remote" and b.extra["id"] == "4712"
    assert b.posted_at is not None and b.posted_at.isoformat() == "2026-10-06T05:00:00"  # pubDate


def test_resume_past_the_single_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(
        Likeit(), handler_for(load_fixture("likeit/rss.xml")), board="x", start_page=1
    )
    assert pages == []


def test_url_patterns() -> None:
    assert detect("https://rekrymesta.likeit.fi/jsp/duuni/AdvertList.jsp") == (
        "likeit",
        "rekrymesta",
    )
    assert detect("likeit:go-on") == ("likeit", "go-on")
    assert detect("https://www.likeit.fi/") is None
