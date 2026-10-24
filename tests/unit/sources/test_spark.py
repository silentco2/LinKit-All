from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import spark
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_search_maps_active_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("spark/list.json"))

    pages = search_pages(spark.Spark(), handler, board="volo")
    assert seen[0].headers["X-workspace"] == "volo"  # how the shared API picks the tenant
    assert len(pages) == 1 and len(pages[0]) == 1  # the closed posting (status 30) is skipped
    job = pages[0][0]
    assert job.title == "Business Development Assistant" and job.company == "Volo"
    assert job.url == "https://volo.spark.work/career/job/203/Business-Development-Assistant"
    assert job.description == "Build & grow." and job.remote == "onsite"
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-07-14"
    assert job.extra == {"board": "volo", "id": "203"} and job.ats == "spark"


def test_paging(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(spark, "_SIZE", 1)
    first = load_fixture("spark/list.json")["items"][:1]

    def handler(req: httpx.Request) -> httpx.Response:
        page = int(req.url.params["pageNumber"])
        item = {**first[0], "id": 200 + page}
        return httpx.Response(200, json={"pageCount": 2, "items": [item]})

    calls: list[str] = []
    pages = search_pages(spark.Spark(), handler, board="volo", calls=calls)
    assert [p[0].extra["id"] for p in pages] == ["201", "202"] and len(calls) == 2
    calls.clear()
    assert (
        search_pages(spark.Spark(), handler, board="volo", start_page=1, calls=calls)[0][0].extra[
            "id"
        ]
        == "202"
        and len(calls) == 1
    )


def test_url_patterns() -> None:
    assert detect("https://volo.spark.work/career/job/203/x") == ("spark", "volo")
    assert detect("https://hub.spark.work/api/jobOpenings") is None
    assert detect("spark:volo") == ("spark", "volo")
