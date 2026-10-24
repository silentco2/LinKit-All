from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import paradox
from linkit_all.sources.ats.paradox import Paradox
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BOARD = "olivia.paradox.ai/JovieofNewportBeach"


def make_handler(
    load_fixture: Callable[[str], Any], calls: list[str] | None = None, refuse: bool = False
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(req.url))
        assert req.headers["X-Requested-With"] == "XMLHttpRequest"  # the API answers 404 without
        q = req.url.params
        assert q["compsite_slug"] == "jovieofnewportbeach"  # the site, lower-cased
        if req.url.path == "/api/job-list-site-ui/search-job":
            if q["page"] != "1":
                return httpx.Response(200, json={"success": True, "jobs": [], "total_jobs": 0})
            return httpx.Response(200, json=load_fixture("paradox/listing.json"))
        if refuse:
            return httpx.Response(403)
        name = f"paradox/detail_{q['job_id']}.json"
        try:
            return httpx.Response(200, json=load_fixture(name))
        except FileNotFoundError:  # the platform's answer for a job id it does not know
            return httpx.Response(200, json=load_fixture("paradox/detail_unknown.json"))

    return handler


def test_listing_then_widget_details(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Paradox(), make_handler(load_fixture, calls), board=BOARD)
    assert "limit=100" in calls[0]
    jobs = {j.extra["id"]: j for j in pages[0]}
    assert set(jobs) == {"P1-6681374-1", "P1-6376329-2"}  # the unknown posting has no body
    j = jobs["P1-6376329-2"]
    assert j.title == "On-Call Nanny in OC/LA (ALL AGES)" and j.company == "Jovie of Newport Beach"
    assert j.url == "https://olivia.paradox.ai/co/JovieofNewportBeach/Job?job_id=P1-6376329-2"
    assert j.location == "Long Beach CA 90806, United States" and j.ats == "paradox"
    assert "Hello," in j.description and "<" not in j.description
    assert j.posted_at is not None and j.posted_at.date().isoformat() == "2026-09-23"  # yy-mm-dd
    assert j.extra["board"] == BOARD.lower()


def test_refused_details_leave_the_postings_out(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(Paradox(), make_handler(load_fixture, refuse=True), board=BOARD) == [[]]


def test_foreign_rows_are_not_followed(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("search-job"):
            row = {
                "job_title": "X",
                "original_apply_url": "https://evil.example/co/jovieofnewportbeach/Job?job_id=1",
            }
            return httpx.Response(200, json={"success": True, "total_jobs": 1, "jobs": [row]})
        raise AssertionError("a row that links elsewhere must not be fetched")

    assert search_pages(Paradox(), handler, board=BOARD) == [[]]


def test_paging_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paradox, "PAGE", 2)
    calls: list[str] = []
    handler = make_handler(load_fixture, calls)
    search_pages(Paradox(), handler, board=BOARD, start_page=1, calls=calls)
    assert "limit=2&page=2" in calls[0]


def test_unsuccessful_listing_and_bad_board(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False})

    with pytest.raises(ValueError, match="success=false"):
        search_pages(Paradox(), handler, board=BOARD)
    with pytest.raises(ValueError, match=r"paradox.ai"):
        search_pages(Paradox(), handler, board="evil.example.com/site")


def test_url_patterns() -> None:
    url = "https://olivia.paradox.ai/co/JovieofNewportBeach/Job?job_id=P1-1-1"
    assert detect(url) == ("paradox", BOARD)
    assert detect(f"paradox:{BOARD}") == ("paradox", BOARD)
