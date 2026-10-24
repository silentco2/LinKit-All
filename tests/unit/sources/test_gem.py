import json
from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats import gem
from linkit_all.sources.ats.gem import Gem
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if body["operationName"] == "JobBoardList":
            return httpx.Response(200, json=load_fixture("gem/list.json"))
        ext = body["variables"]["extId"]
        if ext == "X3":  # the posting disappeared between list and detail
            return httpx.Response(200, json={"errors": [{"message": "gone"}], "data": None})
        return httpx.Response(200, json=load_fixture(f"gem/detail_{ext.lower()}.json"))

    return handler


def test_list_then_details(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Gem(), make_handler(load_fixture), board="go-cadre")
    assert len(pages) == 1 and [j.title for j in pages[0]] == [
        "Backend Engineer",
        "Remote SRE",
        "Gone Soon",
    ]
    a, b, c = pages[0]
    assert a.url == "https://jobs.gem.com/go-cadre/X1" and a.company == "Go Cadre"
    assert a.location == "San Diego, USA" and a.remote == "onsite"
    assert "Build" in a.description and "Python" in a.description
    assert a.posted_at is not None and a.posted_at.year == 2026
    assert b.remote == "remote" and b.location == "COL"
    assert c.description == "" and c.posted_at is None  # a failed detail keeps the stub
    assert a.extra == {"board": "go-cadre", "id": "X1"}


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(gem, "CHUNK", 2)
    handler = make_handler(load_fixture)
    assert [len(p) for p in search_pages(Gem(), handler, board="b")] == [2, 1]
    assert [j.title for p in search_pages(Gem(), handler, board="b", start_page=1) for j in p] == [
        "Gone Soon"
    ]


def test_list_error_raises(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    import pytest

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "boom"}], "data": None})

    with pytest.raises(ValueError, match="boom"):
        search_pages(Gem(), handler, board="b")


def test_fetch_details_from_url(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(source="gem", url="https://jobs.gem.com/go-cadre/X2", title="t", company="c")
    full = fetch_details(Gem(), make_handler(load_fixture), stub)
    assert full.description == "Keep it up."


def test_url_patterns() -> None:
    assert detect("https://jobs.gem.com/go-cadre") == ("gem", "go-cadre")
    assert detect("gem:go-cadre") == ("gem", "go-cadre")
