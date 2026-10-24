from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import paycor
from linkit_all.sources.ats.paycor import Paycor, posting_id
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BOARD = "8a7883c664f8df9e0165119e33353606"
URL = "https://recruitingbypaycor.com/career/JobIntroduction.action?clientId="


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path.endswith("CareerHome.action"):
            return httpx.Response(200, text=load_fixture("paycor/listing.html"))
        if req.url.params["id"].endswith("548a"):
            return httpx.Response(200, text=load_fixture("paycor/detail.html"))
        return httpx.Response(200, text=load_fixture("paycor/inactive.html"))  # 200, no fields

    return handler


def test_posting_id_filters() -> None:
    assert posting_id(f"{URL}{BOARD}&id=abc123", BOARD) == "abc123"
    assert posting_id(f"{URL}{BOARD.upper()}&id=abc123", BOARD) == "abc123"  # hex, either case
    assert posting_id(f"{URL}{BOARD}", BOARD) == ""  # the board's "submit your resume" link
    assert posting_id(f"{URL}4028f88b2456f3b601247ccb93d40fa2&id=abc123", BOARD) == ""
    assert posting_id("https://recruitingbypaycor.com/career/CareerHome.action", BOARD) == ""
    assert posting_id("/about", BOARD) == ""


def test_listing_then_detail(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Paycor(), make_handler(load_fixture), board=BOARD, calls=calls)
    (job,) = pages[0]  # the inactive posting answers 200 without fields and is dropped
    assert len([c for c in calls if "JobIntroduction" in c]) == 2  # duplicates, strangers skipped
    assert job.title == "Line Cook, Grill"  # the leading <b>Position:</b> label is not the value
    assert job.location == "Remote - Dublin, Ireland" and job.remote == "remote"
    assert job.description == "Cook the food." and job.ats == "paycor"
    assert job.url == f"{URL}{BOARD}&id=8a78879e9f4435c7019f6b4f5c3a548a"
    assert job.extra == {"board": BOARD, "id": "8a78879e9f4435c7019f6b4f5c3a548a"}


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paycor, "CHUNK", 1)
    handler = make_handler(load_fixture)
    assert [len(p) for p in search_pages(Paycor(), handler, board=BOARD)] == [1, 0]
    assert [len(p) for p in search_pages(Paycor(), handler, board=BOARD, start_page=1)] == [0]


def test_bad_board_and_url_patterns(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="client id"):
        search_pages(Paycor(), lambda r: httpx.Response(200), board="a b")
    assert detect(f"{URL}{BOARD}&id=abc") == ("paycor", BOARD)
    assert detect(f"https://recruitingbypaycor.com/career/CareerHome.action?clientId={BOARD}") == (
        "paycor",
        BOARD,
    )
