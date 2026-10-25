import json
from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import emagine
from linkit_all.sources.companies.emagine import HOST, Emagine


def test_search_posts_the_filter_block_and_maps_ads(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=load_fixture("emagine/search.json"))

    pages = search_pages(Emagine(), handler, board=HOST)
    body = bodies[0]
    assert body["skipCount"] == 0 and body["sorting"] == "Id asc"
    assert body["supportedLanguageId"] == "EN"
    assert all(body["filter"][k] == [] for k in body["filter"]) and len(body["filter"]) == 8
    remote, hybrid, part = pages[0]
    assert remote.title == "Senior AI Platform Engineer" and remote.company == "emagine"
    assert remote.location == "Portugal" and remote.remote == "remote"
    assert hybrid.location == "Warsaw, Mazovia, Poland" and hybrid.remote == "hybrid"
    assert hybrid.url == "https://portal.emagine.org/jobs/178953/junior-business-analyst"
    assert part.location == "" and part.remote is None  # a null location object
    assert [s.extra["employment"] for s in pages[0]] == ["contract", "contract", "part_time"]
    assert remote.posted_at is None and hybrid.extra["id"] == "178953"


def test_pages_by_skip_count_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], monkeypatch: Any
) -> None:
    monkeypatch.setattr(emagine, "PAGE", 2)
    skips: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        skip = json.loads(req.content)["skipCount"]
        skips.append(skip)
        items = [{"id": i + 1, "title": f"Job {i}"} for i in range(skip, min(skip + 2, 3))]
        return httpx.Response(200, json={"items": items, "totalCount": 3})

    pages = search_pages(Emagine(), handler, board=HOST)
    assert skips == [0, 2] and [len(p) for p in pages] == [2, 1]
    skips.clear()
    search_pages(Emagine(), handler, board=HOST, start_page=1)
    assert skips == [2]


def test_details_and_task(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=load_fixture("emagine/detail.json"))

    stub = JobStub(
        source="emagine",
        url="https://portal.emagine.org/jobs/178953/junior-business-analyst",
        title="J",
        company="emagine",
    )
    full = fetch_details(Emagine(), handler, stub)
    assert seen == ["/api/JobAds/details/178953/EN"]
    assert (
        "Support a retail client." in full.description and "Write user stories" in full.description
    )
    assert Emagine().tasks(SearchConfig())[0].board == HOST
