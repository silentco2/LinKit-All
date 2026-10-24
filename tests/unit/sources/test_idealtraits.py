import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.idealtraits import (
    IdealTraits,
    benefit_lists,
    business_id,
    cards,
    list_url,
)
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http

BOARD = "1162292"  # "MTE2MjI5Mg==" in a career-site URL


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(
    load_fixture: Callable[[str], Any], listing: Any = None, seen: list[httpx.Request] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path.endswith("/careers"):
            return httpx.Response(200, json=listing or load_fixture("idealtraits/listing.json"))
        job_id = req.url.path.rsplit("/", 1)[-1].removesuffix("CPG")
        try:
            return httpx.Response(200, text=load_fixture(f"idealtraits/job_{job_id}.html"))
        except FileNotFoundError:
            return httpx.Response(404)

    return handler


def test_board_id_forms() -> None:
    assert business_id("1162292") == "1162292"
    assert business_id("MTE2MjI5Mg==") == "1162292"
    assert business_id("MTE2MjI5Mg%3D%3D") == "1162292"
    with pytest.raises(ValueError, match="business id"):
        business_id("not-an-id")
    assert (
        list_url("1162292", 2) == "https://app.idealtraits.com/company/MTE2MjI5Mg==/careers?page=2"
    )


def test_cards_ignore_the_commented_out_copy(load_fixture: Callable[[str], Any]) -> None:
    found = cards(load_fixture("idealtraits/listing.json")["joblist"])
    assert [c[0] for c in found] == ["369444", "367541", "367535", "367487", "354262"]
    assert found[0][2] == "Personal Lines Account Manager"
    assert cards("") == []


def test_search_reads_the_listing_then_each_posting(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []
    pages = search_pages(IdealTraits(), _serve(load_fixture, seen=seen), board=BOARD)
    assert len(pages) == 1 and len(pages[0]) == 5
    listing_req = next(r for r in seen if r.url.path.endswith("/careers"))
    assert listing_req.headers["X-Requested-With"] == "XMLHttpRequest"
    first = pages[0][0]
    assert first.title == "Personal Lines Account Manager"
    assert first.url == "https://app.idealtraits.com/career/Comma-Insurance/369444CPG"
    assert first.company == "Comma Insurance" and first.ats == "idealtraits"
    assert first.location == "Oklahoma City, OK, USA"
    assert first.remote == "hybrid"  # "Hybrid Remote" on the page
    assert (first.salary_min, first.salary_max) == (45000, 55000)
    assert first.salary_currency == "USD" and first.salary_interval == "year"
    assert first.posted_at is not None
    assert "###" not in first.description and "Health Insurance" in first.description
    assert first.extra["board"] == BOARD and first.extra["id"] == "369444"
    assert {s.remote for s in pages[0]} == {"hybrid", "remote"}


def test_short_listing_is_an_error_not_a_truncated_board(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    listing = {**load_fixture("idealtraits/listing.json"), "jobcount": 9}
    with pytest.raises(ValueError, match="read 5 postings of 9"):
        search_pages(IdealTraits(), _serve(load_fixture, listing), board=BOARD)


def test_empty_board(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    empty = load_fixture("idealtraits/empty.json")
    assert search_pages(IdealTraits(), _serve(load_fixture, empty), board=BOARD) == [[]]
    assert search_pages(IdealTraits(), _serve(load_fixture, empty), board=BOARD, start_page=1) == []


def test_posting_page_gone_is_skipped(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    listing = json.loads(json.dumps(load_fixture("idealtraits/listing.json")))
    listing["joblist"] = listing["joblist"].replace("354262CPG", "999999CPG")
    pages = search_pages(IdealTraits(), _serve(load_fixture, listing), board=BOARD)
    assert sorted(s.extra["id"] for s in pages[0]) == ["367487", "367535", "367541", "369444"]


def test_benefit_lists() -> None:
    html = benefit_lists("<p>Perks</p>Paid Time Off (PTO)###Health Insurance###<br />")
    assert (
        html == "<p>Perks</p><ul><li>Paid Time Off (PTO)</li><li>Health Insurance</li></ul><br />"
    )


def test_url_patterns() -> None:
    url = "https://app.idealtraits.com/Comma-Insurance/MTE2MjI5Mg==/careers"
    assert detect(url) == ("idealtraits", "MTE2MjI5Mg==")
    assert detect("idealtraits:1162292") == ("idealtraits", "1162292")
