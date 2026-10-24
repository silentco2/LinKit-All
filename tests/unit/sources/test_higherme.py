from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import higherme
from linkit_all.sources.ats.higherme import HigherMe
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BRAND = "6078977d8dfec"


def test_search_filters_by_brand_and_maps_published_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("higherme/jobs.json"))

    pages = search_pages(HigherMe(), handler, board=BRAND)
    assert len(seen) == 1
    q = seen[0].url.params
    assert q["filters[brand.id]"] == BRAND and q["limit"] == "100" and q["page"] == "1"
    assert [s.title for s in pages[0]] == ["Server", "Bartender", "Host"]  # the draft is dropped
    server, bartender, _ = pages[0]
    assert server.url == "https://app.higherme.com/jobs/607afbaf44f91"
    assert (
        server.company == "Camp" and server.location == "Greenville, South Carolina, United States"
    )
    assert server.description.startswith("Camp, is seeking enthusiastic")
    assert "Requirements\nTeam player" in server.description
    assert "About\nModern American Eatery" in server.description
    assert server.salary_min is None and server.posted_at is None
    assert (bartender.salary_min, bartender.salary_max) == (52000, 60000)
    assert (bartender.salary_currency, bartender.salary_interval) == ("USD", "year")
    assert server.extra["board"] == BRAND and server.extra["id"] == "607afbaf44f91"


def test_paging_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = load_fixture("higherme/jobs.json")
    rows = jobs["data"][:3]

    def handler(req: httpx.Request) -> httpx.Response:
        page = int(req.url.params["page"])
        meta = {"last_page": 2, "total": 3}
        return httpx.Response(200, json={"data": rows[:2] if page == 1 else rows[2:], "meta": meta})

    calls: list[str] = []
    pages = search_pages(HigherMe(), handler, board=BRAND, calls=calls)
    assert [len(p) for p in pages] == [2, 1] and len(calls) == 2
    calls.clear()
    pages = search_pages(HigherMe(), handler, board=BRAND, start_page=1, calls=calls)
    assert [len(p) for p in pages] == [1] and "page=2" in calls[0]


def test_an_ignored_brand_filter_is_an_error(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = lambda req: httpx.Response(200, json=load_fixture("higherme/jobs.json"))  # noqa: E731
    with pytest.raises(ValueError, match="asked for brand"):
        search_pages(HigherMe(), handler, board="someotherbrand")


def test_salary_needs_a_known_country() -> None:
    row = {
        "id": "x",
        "attributes": {
            "title": "Cook",
            "status": "published",
            "salary": {"min": 15, "max": 18, "type": "hourly"},
        },
        "relations": {"location": {"attributes": {"country": {"short": "GB", "name": "UK"}}}},
    }
    assert HigherMe.stub(row, BRAND).salary_currency is None  # type: ignore[union-attr]
    row["relations"]["location"]["attributes"]["country"]["short"] = "CA"  # type: ignore[index]
    stub = HigherMe.stub(row, BRAND)
    assert stub is not None and stub.salary_currency == "CAD" and stub.salary_interval == "hour"
    assert higherme.MAX_PAGES >= 1


def test_url_patterns() -> None:
    assert detect(f"https://app.higherme.com/careers/{BRAND}") == ("higherme", BRAND)
    assert detect("https://app.higherme.com/jobs/607afbaf44f91") is None  # names no brand
