from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import lamoda
from linkit_all.sources.companies.lamoda import HOST, Lamoda


def test_list_maps_vacancies(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Lamoda(),
        lambda req: httpx.Response(200, json=load_fixture("lamoda/list.json")),
        board=HOST,
        calls=calls,
    )
    assert "pagination%5Blimit%5D=100&pagination%5Bstart%5D=0" in calls[0]
    a, b = pages[0]
    assert a.title == "Менеджер" and a.company == "Lamoda" and a.location == "Москва"
    assert a.url == "https://job.lamoda.ru/vacancies/moskva/menedzher-2466"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-06-11T16:04:39"
    assert a.remote is None and b.remote == "remote"  # "Удалённо"
    assert a.description == "" and a.extra == {"id": "2466"}  # the body comes from fetch_details


def test_paging_by_offset(
    search_pages: Callable[..., list[list[JobStub]]], monkeypatch: Any
) -> None:
    monkeypatch.setattr(lamoda, "PAGE", 2)
    starts: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        start = int(req.url.params["pagination[start]"])
        starts.append(str(start))
        rows = [
            {"id": i + 1, "name": f"J{i}", "slug": f"c/j-{i}"}
            for i in range(start, min(start + 2, 3))
        ]
        return httpx.Response(200, json={"data": rows, "meta": {"total": 3}})

    pages = search_pages(Lamoda(), handler, board=HOST)
    assert starts == ["0", "2"] and [len(p) for p in pages] == [2, 1]


def test_details_join_the_four_blocks(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=load_fixture("lamoda/detail.json"))

    # the enrich stage rebuilds the stub from the DB: extra["id"] is the database id there
    stub = JobStub(
        source="lamoda",
        url="https://job.lamoda.ru/vacancies/moskva/menedzher-2466",
        title="Менеджер",
        company="Lamoda",
        extra={"id": "db-row-id"},
    )
    full = fetch_details(Lamoda(), handler, stub)
    assert seen == ["/api/hr/vacancies/2466"]
    for part in ("Intro.", "Duties.", "Req", "Cond."):
        assert part in full.description
    assert "alert" not in full.description


def test_details_fall_back_to_common_and_task(fetch_details: Callable[..., JobStub]) -> None:
    body = {"data": {"attributes": {"introduction": "", "common": "<p>Whole body.</p>"}}}
    stub = JobStub(
        source="lamoda", url="https://job.lamoda.ru/vacancies/spb/x-9", title="X", company="L"
    )
    full = fetch_details(Lamoda(), lambda req: httpx.Response(200, json=body), stub)
    assert full.description == "Whole body."
    assert Lamoda().tasks(SearchConfig())[0].board == HOST
