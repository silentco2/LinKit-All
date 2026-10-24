import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.crelate import Crelate
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BOARD = "careertree/ec546cba-84d5-4d8a-97e5-52e8ef47db08"


def test_search_maps_portal_jobs(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    data = load_fixture("crelate/get_all_jobs.json")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=data)

    pages = search_pages(Crelate(), handler, board=BOARD)
    envelope = json.loads(seen[0].url.params["requestEnvelope"])
    assert envelope["OrganizationId"] == "ec546cba-84d5-4d8a-97e5-52e8ef47db08"
    assert len(pages) == 1 and len(pages[0]) == 2  # the posting without an id is dropped
    first, second = pages[0]
    assert first.title == "Physical Therapist Assistant"
    assert first.company == "Career Tree Network (Discovery At Home)"
    assert first.location == "Tampa, FL"
    assert first.url == "https://jobs.crelate.com/portal/careertree/job/mw9k5zg5f4m8hfigm4p8hnzz6w"
    assert "Home Health role." in first.description and "alert" not in first.description
    assert first.posted_at is not None and first.posted_at.year == 2026
    assert first.extra["id"] == "2ab5a6fa-8b64-414a-9cd0-d6de0804d599" and first.ats == "crelate"
    # no CompanyName -> the slug; no JobCode -> the code from Url; country when no city/state
    assert second.company == "Careertree" and second.location == "United States"
    assert second.url.endswith("/portal/careertree/job/abc123") and second.remote == "remote"


def test_portal_error_and_bad_board(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    err = {"IsError": True, "ErrorMessage": "bad org", "Jobs": []}
    with pytest.raises(ValueError, match="bad org"):
        search_pages(Crelate(), lambda req: httpx.Response(200, json=err), board=BOARD)
    with pytest.raises(ValueError, match="must be"):
        search_pages(Crelate(), lambda req: httpx.Response(200, json={}), board="careertree")


def test_shorthand_only() -> None:
    # A portal URL does not carry the organization id, so only the shorthand names a board.
    assert detect("https://jobs.crelate.com/portal/careertree") is None
    assert detect(f"crelate:{BOARD}") == ("crelate", BOARD)
