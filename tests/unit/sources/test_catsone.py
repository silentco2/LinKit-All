from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.catsone import Catsone
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.careers import Unsupported


def test_search_listing(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    html = load_fixture("catsone/listing.html")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        assert req.url.path == "/careers"
        return httpx.Response(200, text=html)

    pages = search_pages(Catsone(), handler, board="acme.catsone.com")
    assert len(pages) == 1 and len(pages[0]) == 2  # duplicate row and non-job link dropped
    first, second = pages[0]
    assert first.title == "Sales Development Rep"
    assert first.url == "https://acme.catsone.com/careers/90438/jobs/16831828-sdr"
    assert first.company == "Acme" and first.location == "Sao Paulo, Brazil"
    assert first.extra["id"] == "16831828" and first.ats == "catsone"
    assert second.remote == "remote"
    assert search_pages(Catsone(), handler, board="acme.catsone.com", start_page=1) == []


def test_robots_disallow_stops_the_board(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nDisallow: /")

    with pytest.raises(Unsupported):
        search_pages(Catsone(), handler, board="acme.catsone.com")


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    html = load_fixture("catsone/detail.html")
    stub = JobStub(
        source="catsone",
        url="https://acme.catsone.com/careers/90438/jobs/1",
        title="t",
        company="c",
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if req.url.path == "/robots.txt" else 200, text=html)

    full = fetch_details(Catsone(), handler, stub)
    assert "Sell things." in full.description and "alert" not in full.description
    assert "Ignored Header" not in full.description


def test_url_patterns() -> None:
    assert detect("https://acme.catsone.com/careers/90438") == ("catsone", "acme.catsone.com")
    assert detect("catsone:jobs.acme.com") == ("catsone", "jobs.acme.com")
