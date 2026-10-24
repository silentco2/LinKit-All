from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.hireclick import HireClick, _posted
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

GUID = "FC454F65-3845-46EA-AB2F-9D91956D90AF"


def _handler(load_fixture: Callable[[str], Any], calls: list[str]) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(str(req.url))
        if req.url.path == "/jobboard/jobboard.aspx":
            return httpx.Response(200, text=load_fixture("hireclick/jobboard.html"))
        if req.url.path.startswith("/api/"):
            # The body is a JSON string holding the JSON document.
            return httpx.Response(200, text=load_fixture("hireclick/jobs.json"))
        job_id = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, text=load_fixture(f"hireclick/view_{job_id}.html"))

    return handler


def test_board_page_guid_then_json_string_listing(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(HireClick(), _handler(load_fixture, calls), board="williamsnd")
    assert calls == [
        "https://williamsnd.hireclick.com/jobboard/jobboard.aspx",
        f"https://williamsnd.hireclick.com/api/Controllers/JobBoard/GetSettingsAndJobs?orgGUID={GUID}",
    ]  # the listing has no bodies: no posting page is read here
    assert len(pages) == 1 and len(pages[0]) == 2  # the duplicate id is dropped
    first = pages[0][0]
    assert first.title == "Adolescent Care Attendant (2pm - midnight)"
    assert first.url == (
        "https://williamsnd.hireclick.com/jb/adolescent-care-attendant-2pm-midnight/view/254235"
    )
    assert first.company == "Williamsnd" and first.location == "WILLISTON"
    assert first.description == "" and first.ats == "hireclick"
    assert first.extra["id"] == "254235" and first.extra["board"] == "williamsnd"


def test_resume_past_the_single_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(HireClick(), _handler(load_fixture, []), board="williamsnd", start_page=1)
    assert pages == []


def test_unknown_tenant_has_no_guid(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    import pytest

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if req.url.path == "/robots.txt" else 200, text="<html>x</html>")

    with pytest.raises(ValueError, match="no organisation id"):
        search_pages(HireClick(), handler, board="nobody")


def test_details_read_the_posting_page(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    url = "https://williamsnd.hireclick.com/jb/adolescent-care-attendant-2pm-midnight/view/254235"
    stub = JobStub(source="hireclick", url=url, title="Adolescent Care Attendant", company="W")
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        seen.append(req.url.path)
        return httpx.Response(200, text=load_fixture("hireclick/view_254235.html"))

    out = fetch_details(HireClick(), handler, stub)
    assert seen == ["/jb/adolescent-care-attendant-2pm-midnight/view/254235"]
    assert out.description.startswith("APPLY ONLINE AT")
    assert "<div" not in out.description and "style" not in out.description
    assert out.posted_at is not None and out.posted_at.year == 2026
    assert out.location  # from the JobPosting's postal address
    assert out.title == stub.title and out.company == "W"


def test_a_taken_down_posting_redirects_to_the_board(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    url = "https://williamsnd.hireclick.com/jb/gone/view/1"
    stub = JobStub(source="hireclick", url=url, title="Gone", company="W")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path.startswith("/jb/"):
            return httpx.Response(302, headers={"Location": "/jobboard/"})
        return httpx.Response(200, text=load_fixture("hireclick/jobboard.html"))

    assert fetch_details(HireClick(), handler, stub) == stub


def test_us_dates_and_url_patterns() -> None:
    posted = _posted("9/16/2026 10:58:32 AM")
    assert posted is not None and (posted.month, posted.day, posted.hour) == (9, 16, 10)
    assert _posted("garbage") is None
    assert detect("https://williamsnd.hireclick.com/jb/x/view/254235") == (
        "hireclick",
        "williamsnd",
    )
