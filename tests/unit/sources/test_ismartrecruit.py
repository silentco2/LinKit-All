import base64
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.ismartrecruit import ISmartRecruit, posting_id, readable_board, unwrap
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http

BOARD = "caglobalint.com_1"
TOKEN = "E7p" + base64.b64encode(BOARD.encode()).decode().rstrip("=") + "Q9e"
HREF = "https://app.ismartrecruit.com/jobDescription?x=E7pY2FnbG9iYWxpbnQuY29tXzE0MjA4NjIzX1dfZW4=Q9e&view=grid"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/openJobWebsite":
            return httpx.Response(200, text=load_fixture("ismartrecruit/listing.html"))
        if req.url.path == "/jobDescription":
            return httpx.Response(200, text=load_fixture("ismartrecruit/detail.html"))
        return httpx.Response(404)

    return handler


def test_tokens() -> None:
    assert (
        unwrap("E7pY2FnbG9iYWxpbnQuY29tXzE0MjA4NjIzX1dfZW4=Q9e") == "caglobalint.com_14208623_W_en"
    )
    assert unwrap("nope") == "" and unwrap("E7p!!!Q9e") == ""
    assert posting_id(HREF) == "14208623"
    assert posting_id("https://app.ismartrecruit.com/jobDescription?x=bad") == ""
    assert readable_board(BOARD) == BOARD
    assert readable_board(TOKEN[3:-3]) == BOARD  # the form a pasted widget url carries


def test_search_reads_the_grid(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(ISmartRecruit(), _serve(load_fixture), board=BOARD, calls=calls)
    assert f"tenantId={TOKEN}" in calls[-1]
    assert len(pages) == 1 and len(pages[0]) == 2
    first, second = pages[0]
    assert first.title.startswith("On-Site Mining Engineer") and first.title.endswith("Namibia")
    assert first.location == "Namibia" and first.company == "Caglobalint"
    assert first.url.startswith("https://app.ismartrecruit.com/jobDescription?x=E7p")
    assert first.extra == {"board": BOARD, "id": "14208623"} and first.ats == "ismartrecruit"
    assert second.extra["id"] == "14208625"
    # the base64 board of a pasted URL gives the same tenant
    again = search_pages(ISmartRecruit(), _serve(load_fixture), board=TOKEN[3:-3], calls=calls)
    assert again[0][0].extra["board"] == BOARD
    assert search_pages(ISmartRecruit(), _serve(load_fixture), board=BOARD, start_page=1) == []


def test_fetch_details_reads_og_description(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(source="ismartrecruit", url=HREF, title="", company="Caglobalint")
    done = fetch_details(ISmartRecruit(), _serve(load_fixture), stub)
    assert done.description.startswith("Reference Number: 083-1007KV")
    assert "open pit copper project" in done.description
    assert done.title.startswith("On-Site Mining Engineer")  # og:title fills a missing title
    kept = stub.model_copy(update={"description": "kept"})
    assert fetch_details(ISmartRecruit(), _serve(load_fixture), kept).description == "kept"


def test_url_patterns() -> None:
    url = f"https://app.ismartrecruit.com/openJobWebsite?tenantId={TOKEN}&view=grid"
    assert detect(url) == ("ismartrecruit", TOKEN[3:-3])
    assert detect(f"ismartrecruit:{BOARD}") == ("ismartrecruit", BOARD)
