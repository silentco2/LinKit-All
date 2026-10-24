from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.hcshiring import HcsHiring
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def _list_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    pages = {"1": load_fixture("hcshiring/page1.json"), "2": load_fixture("hcshiring/page2.json")}
    return lambda req: httpx.Response(200, json=pages[req.url.params["page"]])


def test_search_walks_every_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(HcsHiring(), _list_handler(load_fixture), board="regencypark", calls=calls)
    assert [len(p) for p in pages] == [10, 6]
    assert calls == [
        "https://regencypark.hcshiring.com/api/jobs?page=1",
        "https://regencypark.hcshiring.com/api/jobs?page=2",
    ]
    first = pages[0][0]
    assert first.title == "Certified Occupational Therapist Assistant - COTA"
    assert first.url == "https://regencypark.hcshiring.com/jobs/hs4dEISPR0ym2tqFezL11A"
    assert first.company == "Regencypark" and first.location == "College Place, WA 99324"
    assert first.extra == {
        "board": "regencypark",
        "id": "hs4dEISPR0ym2tqFezL11A",
        "employment": "PRN",
    }
    assert first.salary_min == 42.0 and first.salary_max == 50.0
    assert first.salary_currency == "USD" and first.salary_interval == "hour"
    assert first.posted_at is not None and first.posted_at.date().isoformat() == "2026-10-19"


def test_resume_starts_at_the_given_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        HcsHiring(), _list_handler(load_fixture), board="regencypark", start_page=1, calls=calls
    )
    assert [len(p) for p in pages] == [6] and len(calls) == 1


def test_internal_only_rows_are_dropped(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    body = {
        "jobs": [
            {"id": "a", "title": "Nurse", "isInternalOnly": False, "city": "X", "state": "WA"},
            {"id": "b", "title": "Staff only", "isInternalOnly": True},
        ],
        "meta": {"totalJobs": 2, "totalPages": 1},
    }
    pages = search_pages(HcsHiring(), lambda req: httpx.Response(200, json=body), board="t")
    assert [s.title for s in pages[0]] == ["Nurse"]


def test_details_fill_the_description(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = HcsHiring.stub({"id": "69Vh-JzX6EaPPt-WP-GBFA", "title": "COTA"}, "regencypark", "R")
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(str(req.url))
        return httpx.Response(200, json=load_fixture("hcshiring/detail_69Vh.json"))

    out = fetch_details(HcsHiring(), handler, stub)
    assert seen == [
        "https://regencypark.hcshiring.com/api/jobDescriptions?id=69Vh-JzX6EaPPt-WP-GBFA"
    ]
    assert "Under the supervision of a Occupational Therapist" in out.description
    assert "<ul>" not in out.description


def test_salary_shapes_and_url_patterns() -> None:
    row = {
        "id": "x",
        "title": "T",
        "publicFieldValues": [{"name": "Salary", "value": "110000.00 Annually"}],
    }
    s = HcsHiring.stub(row, "b", "B")
    assert (s.salary_min, s.salary_max, s.salary_interval) == (110000.0, 110000.0, "year")
    weekly = {
        "id": "x",
        "title": "T",
        "publicFieldValues": [{"name": "Salary", "value": "900 Weekly"}],
    }
    assert HcsHiring.stub(weekly, "b", "B").salary_min is None
    assert detect("https://regencypark.hcshiring.com/jobs/abc") == ("hcshiring", "regencypark")
