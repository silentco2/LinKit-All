from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import geekhunter
from linkit_all.sources.ats.geekhunter import GeekHunter, listing_urls
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/pt/acme/jobs":
            return httpx.Response(200, text=load_fixture("geekhunter/list.html"))
        if path.endswith("/backend-engineer"):
            return httpx.Response(200, text=load_fixture("geekhunter/job_backend.html"))
        return httpx.Response(200, text=load_fixture("geekhunter/job_remote.html"))

    return handler


def test_list_then_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(GeekHunter(), make_handler(load_fixture), board="acme")
    assert len(pages) == 1 and len(pages[0]) == 2
    a, b = pages[0]
    assert a.title == "Backend Engineer" and a.company == "Acme Inc"
    assert a.url == "https://www.geekhunter.com/pt/acme/jobs/backend-engineer"
    assert a.location == "Florianópolis, BRA" and a.remote is None
    assert a.description == "Build things & more."
    assert a.posted_at is not None and a.posted_at.isoformat().startswith("2026-04-02")
    assert a.extra["id"] == "backend-engineer" and a.extra["board"] == "acme"
    assert b.title == "Designer Remoto" and b.remote == "remote"  # no jobLocation at all


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(geekhunter, "CHUNK", 1)
    handler = make_handler(load_fixture)
    assert [len(p) for p in search_pages(GeekHunter(), handler, board="acme")] == [1, 1]
    pages = search_pages(GeekHunter(), handler, board="acme", start_page=1)
    assert [j.title for p in pages for j in p] == ["Designer Remoto"]


def test_listing_urls_edge_cases() -> None:
    assert listing_urls("<html></html>") == []
    assert listing_urls('<script id="itemList" type="application/ld+json">{oops</script>') == []


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    url = "https://www.geekhunter.com/pt/acme/jobs/backend-engineer"
    stub = JobStub(source="geekhunter", url=url, title="t", company="c")
    got = fetch_details(GeekHunter(), make_handler(load_fixture), stub)
    assert got.description == "Build things & more."


def test_url_patterns() -> None:
    assert detect("https://www.geekhunter.com/pt/acme/jobs") == ("geekhunter", "acme")
    assert detect("https://www.geekhunter.com/acme/jobs/backend-engineer") == ("geekhunter", "acme")
    assert detect("geekhunter:acme") == ("geekhunter", "acme")
