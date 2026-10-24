from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.gethired import GetHired
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_feed(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    xml = load_fixture("gethired/rss.xml")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        assert req.url.host == "millersmarketnorwalk.easyapply.co"
        return httpx.Response(200, content=xml.encode())

    pages = search_pages(GetHired(), handler, board="millersmarketnorwalk")
    assert len(pages) == 1 and len(pages[0]) >= 2
    first = pages[0][0]
    assert first.title == "produce clerk" and first.company == "Miller's Market - Norwalk, OH"
    assert first.url == "https://easyapply.co/job/produce-clerk-120"
    assert first.location == "Norwalk, OH" and first.extra["id"] == "produce-clerk-120"
    assert "unloading truck" in first.description
    assert first.posted_at is not None and first.posted_at.year == 2026
    assert pages[0][1].title == "meat dept"  # titles are trimmed


def test_unknown_tenant_redirects_to_login(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/rss":
            return httpx.Response(302, headers={"Location": "https://easyapply.co/login"})
        return httpx.Response(200, text="<html>login</html>")

    with pytest.raises(ValueError, match="no career site"):
        search_pages(GetHired(), handler, board="nobody")


def test_url_patterns() -> None:
    assert detect("https://acme.easyapply.co/") == ("gethired", "acme")
    assert detect("gethired:acme") == ("gethired", "acme")
    assert detect("https://easyapply.co/job/produce-clerk-120") is None
    assert detect("https://www.easyapply.co/") is None
