from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import rwb
from linkit_all.sources.companies.rwb import Rwb


def test_list(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    data = load_fixture("rwb/list.json")
    data["data"]["range"]["count"] = 2
    pages = search_pages(Rwb(), lambda req: httpx.Response(200, json=data))
    assert len(pages) == 1 and len(pages[0]) == 2
    job = pages[0][0]
    assert job.title == "Ведущий продюсер" and job.company == "Wildberries & Russ"
    assert job.url == "https://career.rwb.ru/vacancies/40961" and job.location == "Москва"
    assert job.remote == "hybrid" and job.description == ""


def test_offset_paging(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rwb, "PAGE", 1)
    items = load_fixture("rwb/list.json")["data"]["items"]

    def handler(req: httpx.Request) -> httpx.Response:
        offset = int(req.url.params["offset"])
        data = {"items": items[offset : offset + 1], "range": {"count": 2}}
        return httpx.Response(200, json={"data": data})

    assert [p[0].extra["rwb_id"] for p in search_pages(Rwb(), handler)] == [40961, 40959]
    assert [p[0].extra["rwb_id"] for p in search_pages(Rwb(), handler, start_page=1)] == [40959]


def test_details(fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]) -> None:
    stub = JobStub(
        source="rwb", url="https://career.rwb.ru/vacancies/40961", title="t", company="c"
    )
    got = fetch_details(
        Rwb(), lambda req: httpx.Response(200, json=load_fixture("rwb/detail.json")), stub
    )
    assert got.description.startswith("Объединённая компания Wildberries")
    assert "Управлять ресурсами" in got.description and "Владение инструментами" in got.description
    assert fetch_details(Rwb(), lambda req: httpx.Response(404), stub).description == ""
