import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.gr8people import Gr8People
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

HOST = "etrade.gr8people.com"


def make_handler(
    load_fixture: Callable[[str], Any], seen: list[httpx.Request]
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/jobs":
            return httpx.Response(200, text=load_fixture("gr8people/jobs.html"))
        seen.append(req)
        after = json.loads(req.content)["variables"].get("after")
        return httpx.Response(200, json=load_fixture(f"gr8people/page{2 if after else 1}.json"))

    return handler


def test_cursor_paging_and_fields(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []
    pages = search_pages(Gr8People(), make_handler(load_fixture, seen), board=HOST)
    assert [len(p) for p in pages] == [1, 1]  # the posting without a key is dropped
    assert all(r.headers["Authorization"] == "Bearer eyJhbGciTESTtoken123" for r in seen)
    assert "after" not in json.loads(seen[0].content)["variables"]
    assert json.loads(seen[1].content)["variables"]["after"] == "CURSOR2"
    job = pages[0][0]
    assert job.title == "FSR - Chicago, IL" and job.company == "Etrade"
    assert job.url == f"https://{HOST}/jobs/4709" and job.remote == "onsite"
    assert job.location == "Chicago, IL, USA; Austin, TX, USA"
    assert job.description == "Serve customers."
    assert job.posted_at is not None and job.posted_at.year == 2026
    remote = pages[1][0]
    assert remote.remote == "remote" and remote.location == "Remote, USA"


def test_resume_skips_earlier_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Gr8People(), make_handler(load_fixture, []), board=HOST, start_page=1)
    assert [j.title for p in pages for j in p] == ["Remote Analyst"]


def test_missing_token(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if req.url.path == "/robots.txt" else 200, text="<html></html>")

    with pytest.raises(ValueError, match="no session token"):
        search_pages(Gr8People(), handler, board=HOST)


def test_url_patterns() -> None:
    assert detect(f"https://{HOST}/jobs/4709") == ("gr8people", HOST)
    assert detect("https://acme.workgr8.com/jobs") == ("gr8people", "acme.workgr8.com")
    assert detect(f"gr8people:{HOST}") == ("gr8people", HOST)
