import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import apple
from linkit_all.sources.companies.apple import Apple, describe


def handler(
    load_fixture: Callable[[str], Any], bodies: list[dict[str, Any]] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    pages = {1: "apple/search_page1.json", 2: "apple/search_page2.json"}
    details = load_fixture("apple/details.json")

    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/search":
            body = json.loads(req.content)
            if bodies is not None:
                bodies.append(body)
            return httpx.Response(200, json=load_fixture(pages[body["page"]]))
        pid = req.url.path.rsplit("/", 1)[-1]
        if pid in details:
            return httpx.Response(200, json=details[pid])
        return httpx.Response(404)

    return handle


def test_pages_dedupe_and_fields(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(apple, "PAGE", 2)
    bodies: list[dict[str, Any]] = []
    pages = search_pages(Apple(), handler(load_fixture, bodies), query="swift")
    assert [len(p) for p in pages] == [1, 1]  # the Cupertino row repeats position 200600664
    assert [b["page"] for b in bodies] == [1, 2]
    assert all(b["filters"] == {} and b["query"] == "swift" for b in bodies)
    watch, sre = pages[0][0], pages[1][0]
    assert watch.title == "Software Engineer, Watch Software" and watch.company == "Apple"
    assert (
        watch.url
        == "https://jobs.apple.com/en-us/details/200600664/software-engineer-watch-software"
    )
    assert watch.location == "San Diego" and watch.remote is None
    assert watch.posted_at is not None and watch.posted_at.isoformat() == "2025-12-02T08:30:00"
    assert sre.remote == "remote" and sre.location == "Seattle" and sre.extra == {"id": "200659431"}
    assert watch.description == ""  # the role text comes from fetch_details


def test_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(apple, "PAGE", 2)
    pages = search_pages(Apple(), handler(load_fixture), start_page=1)
    assert [s.title for p in pages for s in p] == ["Site Reliability Engineer"]


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="apple",
        url="https://jobs.apple.com/en-us/details/200600664/software-engineer-watch-software",
        title="t",
        company="Apple",
    )
    out = fetch_details(Apple(), handler(load_fixture), stub)
    assert out.description.startswith("Join the Watch team.\n\nBuild the Watch software.")
    assert "Minimum Qualifications\n- 5+ years experience.\n- Ships software." in out.description
    assert "Preferred Qualifications\n- Swift expertise." in out.description


def test_describe_omits_empty_sections() -> None:
    assert describe({"description": "Just this.", "minimumQualifications": ""}) == "Just this."
