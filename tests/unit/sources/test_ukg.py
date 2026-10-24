import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.ukg import UKG, split_board
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BOARD = "recruiting.ultipro.com/van5000vcscu/a46cbdaa-ca2c-49b6-8d2b-e0ceaafa0e25"


def test_search_posts_the_page_window_and_upgrades_the_brief(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/LoadSearchResults"):
            bodies.append(json.loads(req.content))
            return httpx.Response(200, json=load_fixture("ukg/listing.json"))
        if req.url.params.get("opportunityId") == "id-1":
            return httpx.Response(200, text=load_fixture("ukg/detail.html"))
        return httpx.Response(404)  # id-2 has no detail page: its brief body stays

    pages = search_pages(UKG(), handler, board=BOARD)
    assert bodies == [{"opportunitySearch": {"Top": 50, "Skip": 0}}]
    assert len(pages) == 1
    a, b = pages[0]
    assert a.title == "Backend Engineer" and a.company == "Van5000Vcscu"
    assert a.url == (
        "https://recruiting.ultipro.com/van5000vcscu/JobBoard/a46cbdaa-ca2c-49b6-8d2b-e0ceaafa0e25"
        "/OpportunityDetail?opportunityId=id-1"
    )
    assert a.location == "Vancouver, British Columbia, Canada"
    assert (
        "Full body with a [bracket] and a {brace}" in a.description and "x()" not in a.description
    )
    assert a.extra["employment"] == "full_time" and a.extra["id"] == "id-1" and a.ats == "ukg"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-06-19T22:12:06.752000"
    assert b.description == "brief two" and b.extra["employment"] is None
    assert b.location == "Remote - US" and b.remote == "remote"


def test_pages_until_total_count_and_resumes(
    search_pages: Callable[..., list[list[JobStub]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("linkit_all.sources.ats.ukg.PAGE", 2)  # keeps the detail fetches few
    skips: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if not req.url.path.endswith("/LoadSearchResults"):
            return httpx.Response(404)
        skip = json.loads(req.content)["opportunitySearch"]["Skip"]
        skips.append(skip)
        ids = [i for i in range(skip, min(skip + 2, 3))]
        opps = [
            {"Id": f"o{i}", "Title": "T", "BriefDescription": "b", "Locations": []} for i in ids
        ]
        return httpx.Response(200, json={"totalCount": 3, "opportunities": opps})

    pages = search_pages(UKG(), handler, board=BOARD)
    assert skips == [0, 2] and [len(p) for p in pages] == [2, 1]
    skips.clear()
    search_pages(UKG(), handler, board=BOARD, start_page=1)
    assert skips == [2]


def test_empty_board_and_bad_board(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    empty = lambda req: httpx.Response(200, json={"totalCount": 0, "opportunities": []})  # noqa: E731
    assert search_pages(UKG(), empty, board=BOARD) == []
    with pytest.raises(ValueError, match="host>/<tenant>/<guid"):
        search_pages(UKG(), empty, board="tenant/guid")
    assert split_board("recruiting.ultipro.ca/bur5000burn/3fa0ebc6") == (
        "recruiting.ultipro.ca",
        "bur5000burn",
        "3fa0ebc6",
    )


def test_url_patterns() -> None:
    url = "https://recruiting.ultipro.ca/BUR5000BURN/JobBoard/3fa0ebc6-1111-2222-3333-444455556666/?q=&o=postedDateDesc"
    assert detect(url) == (
        "ukg",
        "recruiting.ultipro.ca/BUR5000BURN/3fa0ebc6-1111-2222-3333-444455556666",
    )
    assert detect(
        "https://rec.pro.ukg.net/ACM1000/JobBoard/3fa0ebc6-1111-2222-3333-444455556666/"
    ) == (
        "ukg",
        "rec.pro.ukg.net/ACM1000/3fa0ebc6-1111-2222-3333-444455556666",
    )
