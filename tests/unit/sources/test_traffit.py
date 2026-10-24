from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import traffit
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


@pytest.fixture(autouse=True)
def _small_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(traffit, "_SIZE", 2)  # the fixtures hold two items a page


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["limit"] == "2"
        page = {"0": "page1", "2": "page2"}[req.url.params["offset"]]
        return httpx.Response(200, json=load_fixture(f"traffit/{page}.json"))

    return handler


def test_search_pages_and_maps(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(traffit.Traffit(), _serve(load_fixture), board="acme", calls=calls)
    assert len(calls) == 2 and [len(p) for p in pages] == [2, 1]  # the id-less advert is dropped
    full, fallback, publish_only = pages[0] + pages[1]
    assert full.title == "Senior Java Engineer" and full.company == "Acme"
    assert full.url == full.apply_url == "https://acme.traffit.com/public/an/abc"
    assert full.location == "Warszawa, Mazowieckie, Polska"
    assert full.description == "Build things" and full.ats == "traffit"
    assert full.posted_at is not None and full.posted_at.year == 2026
    assert full.extra == {"board": "acme", "id": "2001"}
    assert fallback.title == "Remote Fallback Role" and fallback.location == ""  # name; null geo
    assert publish_only.extra["id"] == "2004" and publish_only.location == ""  # advertPublishId


def test_resume_and_errors(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        traffit.Traffit(), _serve(load_fixture), board="acme", start_page=1, calls=calls
    )
    assert len(calls) == 1 and len(pages) == 1
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(traffit.Traffit(), lambda req: httpx.Response(404), board="nobody")


def test_url_patterns() -> None:
    assert detect("https://acme.traffit.com/public/an/abc") == ("traffit", "acme")
    assert detect("traffit:acme") == ("traffit", "acme")
