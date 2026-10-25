from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import amazon
from linkit_all.sources.companies.amazon import Amazon


def handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    data = load_fixture("amazon/search.json")

    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        q = req.url.params
        off, size = int(q["offset"]), int(q["result_limit"])
        return httpx.Response(200, json={**data, "jobs": data["jobs"][off : off + size]})

    return handle


def test_pages_and_fields(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(amazon, "PAGE", 2)
    pages = search_pages(Amazon(), handler(load_fixture))
    assert [len(p) for p in pages] == [2, 1]
    sde = pages[0][0]
    assert sde.title == "Software Development Engineer III" and sde.company == "Amazon"
    assert sde.url == "https://www.amazon.jobs/en/jobs/10449371/sde-iii"
    assert sde.location == "Redmond, Washington, USA" and sde.extra == {"id": "10449371"}
    assert "Build it" in sde.description and "alert" not in sde.description
    assert sde.posted_at is not None and sde.posted_at.isoformat() == "2026-06-15T00:00:00"
    assert pages[0][1].posted_at is None  # blank posted_date
    assert sde.ats == "amazon" and sde.source == "amazon"


def test_resume_limit_and_query(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(amazon, "PAGE", 2)
    assert [
        s.title for p in search_pages(Amazon(), handler(load_fixture), start_page=1) for s in p
    ] == ["SRE"]
    limited = search_pages(Amazon(), handler(load_fixture), limit=2)
    assert [len(p) for p in limited] == [2]
    calls: list[str] = []
    search_pages(Amazon(), handler(load_fixture), query="data engineer", calls=calls)
    assert "base_query=data+engineer" in calls[-1] or "base_query=data%20engineer" in calls[-1]


def test_tasks_one_per_query() -> None:
    cfg = SearchConfig()
    assert [t.query for t in Amazon().tasks(cfg)] == [""]
    cfg.search.queries = ["python", "go"]
    assert [t.query for t in Amazon().tasks(cfg)] == ["python", "go"]
    assert not Amazon().is_enabled(cfg)
    cfg.sources.enabled = ["amazon"]
    assert Amazon().is_enabled(cfg)


def test_error_propagates(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(Amazon(), lambda req: httpx.Response(403))
