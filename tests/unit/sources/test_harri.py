import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import harri
from linkit_all.sources.ats.harri import Harri
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def _handler(load_fixture: Callable[[str], Any], bodies: list[dict[str, Any]]) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        if "/profile/slug/" in req.url.path:
            return httpx.Response(200, json=load_fixture("harri/slug.json"))
        body = json.loads(req.content)
        bodies.append(body)
        return httpx.Response(200, json=load_fixture(f"harri/start{body['start']}.json"))

    return handler


def test_search_pages_by_start_until_hits(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    bodies: list[dict[str, Any]] = []
    pages = search_pages(Harri(), _handler(load_fixture, bodies), board="BrindisaKitchensCareers")
    assert [len(p) for p in pages] == [4, 3]  # 7 hits: start 0, then start 4
    assert [b["start"] for b in bodies] == [0, 4]
    assert all(b["brand_level_ids"] == [4018620] for b in bodies)
    first = pages[0][0]
    assert first.title == "Bartender"
    # The posting's URL names the store's slug, not the board's.
    assert first.url == "https://harri.com/Tapas-Brindisa-Kitchens-Richmond/job/2843559-bartender"
    assert first.company == "Brindisakitchenscareers"
    assert first.location == "Richmond, England, United Kingdom"
    assert pages[0][1].location == "London, United Kingdom"  # the repeated country is written once
    assert first.posted_at is not None and first.posted_at.isoformat() == "2026-10-18T09:09:17"
    assert first.extra["id"] == "2843559"


def test_resume_continues_from_the_page_offset(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(harri, "PAGE_SIZE", 4)
    bodies: list[dict[str, Any]] = []
    pages = search_pages(
        Harri(), _handler(load_fixture, bodies), board="brindisakitchenscareers", start_page=1
    )
    assert [b["start"] for b in bodies] == [4] and [len(p) for p in pages] == [3]


def test_unknown_slug_is_an_error(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"data": "Slug not found"})

    with pytest.raises(ValueError, match="no brand"):
        search_pages(Harri(), handler, board="nope")


def test_details_read_description_and_arrangement(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = Harri.stub(
        {"id": 2845499, "aliasPosition": "District Manager", "brand": {"slug": "Wendy-S-Uk"}},
        "wendys",
        "Wendys",
    )
    assert stub is not None
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=load_fixture("harri/job_2845499.json"))

    out = fetch_details(Harri(), handler, stub)
    assert seen == ["/core-reader/api/v1/profile/job/2845499"]
    assert out.remote == "remote"  # FULLY_REMOTE
    assert out.description.startswith("Lead") and "<div>" not in out.description


def test_details_of_a_closed_posting_are_ignored(
    fetch_details: Callable[..., JobStub],
) -> None:
    stub = Harri.stub({"id": 5, "aliasPosition": "Cook"}, "b", "B")
    assert stub is not None
    body = {"data": {"job": {"status": "EXPIRED", "description": "<p>old</p>"}}}
    assert fetch_details(Harri(), lambda req: httpx.Response(200, json=body), stub) == stub


def test_url_patterns() -> None:
    assert detect("https://harri.com/panera-careers") == ("harri", "panera-careers")
    assert detect("https://harri.com/Tapas-Brindisa-Kitchens-Richmond/job/2843559-bartender") == (
        "harri",
        "Tapas-Brindisa-Kitchens-Richmond",
    )
    assert detect("https://gateway.harri.com/core/api/v1/profile/slug/x") is None
