import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import meituan
from linkit_all.sources.companies.meituan import Meituan


def api(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    """The site's search: filters the fixture by hire type and pages by pageNo/pageSize."""

    def handle(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        code = body["jobType"][0]["code"]
        rows = [
            p
            for p in load_fixture("meituan/technology.json")["data"]["list"]
            if p["jobType"] == code
        ]
        size, no = body["page"]["pageSize"], body["page"]["pageNo"]
        data = {"list": rows[(no - 1) * size : no * size], "page": {"totalCount": len(rows)}}
        return httpx.Response(200, json={"status": 1, "data": data})

    return handle


def test_one_page_of_stubs_per_hire_type(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Meituan(), api(load_fixture))
    assert [len(p) for p in pages] == [3, 1, 1]  # experienced, campus, intern
    job = pages[0][0]
    assert job.title == "数据通道-高级Java开发工程师" and job.company == "Meituan"
    assert job.url == "https://zhaopin.meituan.com/web/position/detail?jobUnionId=4839084480"
    assert job.location == "北京市, 上海市" and job.extra["hire_type"] == "experienced"
    assert "Java 开发" in job.description and job.posted_at is not None
    assert pages[1][0].extra["hire_type"] == "campus"
    assert pages[2][0].extra["hire_type"] == "intern"
    assert (
        search_pages(Meituan(), api(load_fixture), start_page=2)[0][0].extra["hire_type"]
        == "intern"
    )


def test_pages_until_total(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(meituan, "PAGE", 2)
    calls: list[str] = []
    pages = search_pages(Meituan(), api(load_fixture), calls=calls)
    assert [len(p) for p in pages] == [3, 1, 1]
    assert len(calls) == 4  # experienced needs two pages of two, the others one each


def test_bad_answer_fails(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    bad = httpx.Response(200, json={"status": 0, "message": "blocked", "data": None})
    with pytest.raises(ValueError, match="blocked"):
        search_pages(Meituan(), lambda req: bad)
