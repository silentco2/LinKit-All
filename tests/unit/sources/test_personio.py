from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.personio import Personio
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def make_handler(
    load_fixture: Callable[[str], Any], calls: list[str] | None = None, english: bool = True
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(req.url))
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        assert req.url.host == "acme.jobs.personio.com"
        if req.url.path == "/xml":
            if req.url.params.get("language") == "en":
                if not english:
                    return httpx.Response(500)
                return httpx.Response(200, text=load_fixture("personio/feed_en.xml"))
            return httpx.Response(200, text=load_fixture("personio/feed.xml"))
        if req.url.path == "/job/2514154":
            return httpx.Response(200, text=load_fixture("personio/detail.html"))
        return httpx.Response(404)

    return handler


def test_feed_bodies_and_fallbacks(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Personio(), make_handler(load_fixture, calls), board="acme")
    go, platform, game, intern = pages[0]
    assert go.title == "Senior Go Engineer (m/w/d)" and go.location == "Hamburg"
    assert go.url == "https://acme.jobs.personio.com/job/2596159"  # the feed has no URLs
    assert go.company == "Acme" and go.ats == "personio" and go.remote is None
    assert "Build the pipeline." in go.description and "Go" in go.description
    assert go.posted_at is not None and go.posted_at.year == 2026
    assert go.extra["id"] == "2596159" and go.extra["board"] == "acme"
    assert platform.remote == "remote"  # no flag in the feed: inferred from the office
    assert "Design the game." in game.description  # from the English feed
    assert "Your mission as our Marketing Intern." in intern.description  # from the JobPosting
    assert intern.location == "Munich (Hybrid)" and intern.remote == "hybrid"
    assert sum("language=en" in c for c in calls) == 1  # the English feed is fetched once


def test_english_feed_failure_is_not_fatal(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Personio(), make_handler(load_fixture, english=False), board="acme")
    assert len(pages[0]) == 4 and pages[0][2].description == ""


def test_other_domain_and_missing_tenant(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    feed = (
        "<workzag-jobs><position><id>1</id><name>Dev</name><office>Berlin</office>"
        "</position></workzag-jobs>"
    )

    def de_only(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.host.endswith(".de"):
            return httpx.Response(200, text=feed)
        return httpx.Response(404)

    pages = search_pages(Personio(), de_only, board="acme")
    assert pages[0][0].url == "https://acme.jobs.personio.de/job/1"
    with pytest.raises(ValueError, match="no feed"):
        search_pages(Personio(), lambda r: httpx.Response(404), board="acme")


def test_empty_feed_resume_and_bad_board(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<workzag-jobs></workzag-jobs>")

    assert search_pages(Personio(), handler, board="acme") == [[]]
    assert search_pages(Personio(), handler, board="acme", start_page=1) == []
    with pytest.raises(ValueError, match="not a tenant"):
        search_pages(Personio(), handler, board="a/b")


def test_url_patterns() -> None:
    assert detect("https://acme.jobs.personio.com/job/2596159") == ("personio", "acme")
    assert detect("https://beta-gmbh.jobs.personio.de/?language=de") == ("personio", "beta-gmbh")
    assert detect("personio:acme") == ("personio", "acme")
