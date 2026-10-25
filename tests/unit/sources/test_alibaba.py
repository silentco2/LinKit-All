import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import alibaba
from linkit_all.sources.companies.alibaba import TECH, Alibaba


def handler(
    load_fixture: Callable[[str], Any], seen: list[httpx.Request] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if seen is not None:
            seen.append(req)
        page = json.loads(req.content)["pageIndex"]
        return httpx.Response(200, json=load_fixture(f"alibaba/search_page{page}.json"))

    return handle


def test_pages_fields_and_csrf_pair(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(alibaba, "PAGE", 3)  # the fixture pages hold 3 and 2 of 5 postings
    reqs: list[httpx.Request] = []
    pages = search_pages(Alibaba(), handler(load_fixture, reqs))
    assert [len(p) for p in pages] == [3, 2]
    body = json.loads(reqs[0].content)
    assert body["subCategories"] == TECH and body["channel"] == "group_official_site"
    token = reqs[0].headers["X-XSRF-TOKEN"]
    assert token and reqs[0].headers["Cookie"] == f"XSRF-TOKEN={token}"
    assert reqs[1].headers["X-XSRF-TOKEN"] == token  # one token per run
    job = pages[0][0]
    assert job.title == "阿里国际站-Agentic AI 算法工程师-深圳" and job.company == "Alibaba Group"
    assert job.url.endswith("positionId=100048720006") and job.location == "深圳"
    assert job.extra == {"id": "100048720006"} and job.source == "alibaba"
    assert "OKKI" in job.description and "本科" in job.description  # description + requirement
    assert job.posted_at is not None and job.posted_at.year == 2026
    assert pages[0][1].location == "北京; 杭州; 广州; 上海"


def test_resume_and_failure(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(alibaba, "PAGE", 3)
    resumed = search_pages(Alibaba(), handler(load_fixture), start_page=1)
    assert [len(p) for p in resumed] == [2]
    failing = lambda req: httpx.Response(200, json={"success": False, "errorMsg": "csrf"})  # noqa: E731
    with pytest.raises(RuntimeError, match="csrf"):
        search_pages(Alibaba(), failing)
