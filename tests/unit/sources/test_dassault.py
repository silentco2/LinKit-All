from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import dassault
from linkit_all.sources.companies.dassault import Dassault, location_of, parse_cards


def test_poland_cards(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    xml = load_fixture("dassault/search_poland.xml")
    pages = search_pages(Dassault(), lambda req: httpx.Response(200, text=xml), calls=calls)
    assert len(pages) == 1 and len(pages[0]) == 5
    url = next(c for c in calls if "card_search_api" in c)  # the first request reads robots.txt
    assert "r=f/card_content_type/career" in url and "cards%20language/en" in url
    assert "hf=100" in url and "start=0" in url
    by_id = {s.extra["id"]: s for s in pages[0]}
    intern = by_id["550372"]
    assert intern.title == "User Request Engineer Intern" and intern.company == "Dassault Systèmes"
    assert intern.url.startswith("https://www.3ds.com/careers/jobs/")
    assert intern.url.endswith("-550372") and intern.location == "Krakow, Poland"
    assert intern.posted_at is not None and intern.posted_at.isoformat() == "2026-10-12T05:10:32"
    # the card summary is the whole body, entity-escaped inside the XML
    assert len(intern.description) > 1000 and "&lt;" not in intern.description
    assert by_id["550461"].location == "Warsaw, Poland"
    assert intern.source == "dassault" and intern.ats == "dassault"


def test_apostrophe_city(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    xml = load_fixture("dassault/search_netherlands.xml")
    pages = search_pages(Dassault(), lambda req: httpx.Response(200, text=xml))
    assert {s.location for s in pages[0]} == {"'s-Hertogenbosch, Netherlands"}
    assert len(pages[0]) == 4


def test_paging_to_the_stated_total(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dassault, "PAGE", 4)
    first = load_fixture("dassault/search_netherlands.xml").replace('nhits="4"', 'nhits="9"')
    second = load_fixture("dassault/search_poland.xml")

    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=second if req.url.params["start"] == "4" else first)

    pages = search_pages(Dassault(), handle)
    assert [len(p) for p in pages] == [4, 5]
    resumed = search_pages(Dassault(), handle, start_page=1)
    assert [len(p) for p in resumed] == [5]


def test_helpers() -> None:
    cards, total = parse_cards(
        b"<Answer xmlns='exa:com.exalead.search.v10' nhits='7'><hits/></Answer>"
    )
    assert cards == [] and total == 7
    country = "Category/X Type/Regular Country/India City/India, MH, Pune Products/Y Year/Z"
    assert location_of({"content_categories": country}) == "Pune, India"
    assert (
        location_of({"content_categories": country.replace("India, MH, Pune", "India")}) == "India"
    )
    assert location_of({"content_info_2_value": "Somewhere"}) == "Somewhere"


def test_foreign_host_card_is_dropped() -> None:
    card = {"card_id": "1", "content_title": "t", "content_cta_1_url": "https://evil.example/x"}
    assert Dassault().stub(card) is None
