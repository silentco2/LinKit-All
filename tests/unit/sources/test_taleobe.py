import asyncio
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from linkit_all.sources.ats import taleobe
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Task
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http


def _feed(
    load_fixture: Callable[[str], Any], name: str
) -> Callable[[httpx.Request], httpx.Response]:
    return lambda req: httpx.Response(200, text=load_fixture(f"taleobe/{name}.xml"))


def test_feed_url_goes_through_the_dispatcher() -> None:
    parts = urlsplit(taleobe.feed_url("AMERINC:52"))
    assert (parts.netloc, parts.path) == ("tbe.taleo.net", "/dispatcher/servlet/DispatcherServlet")
    query = parse_qs(parts.query)
    assert query["org"] == ["AMERINC"] and query["act"] == ["redirectOrg"]
    assert query["redirectUrl"] == ["https://tbe.taleo.net/ats/servlet/Rss?org=AMERINC&cws=52"]
    assert taleobe.feed_url("amerinc/52") == taleobe.feed_url("AMERINC:52")  # the detector's form
    for bad in ("", "AMERINC", "AMERINC:", ":52", "AMERINC:x", "AMER INC:52"):
        with pytest.raises(Unsupported):
            taleobe.feed_url(bad)


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(taleobe.TaleoBE(), _feed(load_fixture, "feed"), board="AMERINC:52")
    assert len(pages) == 1 and len(pages[0]) == 2
    first, remote = pages[0]
    assert first.title == "Network Contractor - Provider Network Management (PNM)"
    assert (
        first.url
        == "https://phh.tbe.taleo.net/phh02/ats/careers/requisition.jsp?org=AMERINC&cws=52&rid=45049"
    )
    assert first.company == "Amerinc" and first.location == "Baton Rouge, LA"
    assert first.posted_at is not None and first.posted_at.isoformat() == "2026-10-20T13:12:18"
    assert first.extra == {"board": "AMERINC:52", "id": "45049"} and first.ats == "taleobe"
    assert first.description  # the HTML body, not the flattened <description>
    assert remote.location == "Remote, United States" and remote.remote == "remote"


def test_empty_board_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(taleobe.TaleoBE(), _feed(load_fixture, "empty"), board="SIGSOURCE:37") == [
        []
    ]
    handler = _feed(load_fixture, "feed")
    assert search_pages(taleobe.TaleoBE(), handler, board="AMERINC:52", start_page=1) == []


def test_a_board_that_is_gone_redirects_to_an_error_page() -> None:
    async def first_page(handler: Callable[[httpx.Request], httpx.Response]) -> list[JobStub]:
        # the real client follows redirects, which is how the platform says a board is gone
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            task = Task("taleobe", "taleobe:ADELPHI:1", board="ADELPHI:1")
            return [
                s async for page in taleobe.TaleoBE().search(Http(client), task, 0) for s in page
            ]

    for target in (
        "https://phf.tbe.taleo.net/dispatcher/login.jsp?loginErrorMsg=x",
        "https://tbe.taleo.net/errorpages/page_not_found_404.html.en",
        "https://phf.tbe.taleo.net/phf02/ats/rssErrMsg.jsp?org=ADELPHI",
    ):

        def handler(req: httpx.Request, target: str = target) -> httpx.Response:
            if req.url.path == "/dispatcher/servlet/DispatcherServlet":
                return httpx.Response(302, headers={"Location": target})
            return httpx.Response(200, text="<!DOCTYPE html><html><head></head></html>")

        with pytest.raises(Unsupported):
            asyncio.run(first_page(handler))


def test_url_patterns() -> None:
    url = "https://phh.tbe.taleo.net/phh02/ats/careers/requisition.jsp?org=AMERINC&cws=52&rid=45049"
    assert detect(url) == ("taleobe", "AMERINC/52")
    assert detect("taleobe:AMERINC:52") == ("taleobe", "AMERINC:52")
