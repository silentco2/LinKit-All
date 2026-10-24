from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.recruitee import Recruitee
from linkit_all.sources.smartrecruiters import SmartRecruiters


def test_search_pages_and_load_fixture(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    data = load_fixture("recruitee/bunq_offers.json")
    calls: list[str] = []
    pages = search_pages(
        Recruitee(), lambda req: httpx.Response(200, json=data), board="bunq", calls=calls
    )
    assert len(pages) == 1 and pages[0][0].ats == "recruitee"
    assert calls == ["https://bunq.recruitee.com/api/offers/"]


def test_fetch_details_helper(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    detail = load_fixture("smartrecruiters/bosch_posting_detail.json")
    bare = JobStub(
        source="smartrecruiters",
        url="https://jobs.smartrecruiters.com/BoschGroup/744000155868389",
        title="t",
        company="c",
    )
    full = fetch_details(SmartRecruiters(), lambda req: httpx.Response(200, json=detail), bare)
    assert full.description
