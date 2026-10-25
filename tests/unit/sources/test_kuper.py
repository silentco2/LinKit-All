from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.kuper import HOST, Kuper


def handler_for(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda req: httpx.Response(
        200, json=load_fixture(f"kuper/page{req.url.params['page']}.json")
    )


def test_pages_follow_the_pagination_block(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Kuper(), handler_for(load_fixture), board=HOST, calls=calls)
    assert calls == [
        f"https://{HOST}/api/vacancy_pagination/?page=1",
        f"https://{HOST}/api/vacancy_pagination/?page=2",
    ]
    first, second = pages[0][0], pages[1][0]
    assert first.title == "Курьер" and first.company == "Kuper" and first.location == "Москва"
    assert first.url == "https://kuper.ru/rabota/Kurer-v-Kuper-1272"
    assert first.remote == "remote" and second.remote is None  # Удалённый / Офисный
    assert "Deliver things." in first.description and "alert" not in first.description
    assert first.posted_at is None and first.extra["id"] == "uuid-1"
    assert second.url.endswith("Operator-v-Kuper-1273")


def test_resume_and_empty_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Kuper(), handler_for(load_fixture), board=HOST, start_page=1)
    assert len(pages) == 1 and pages[0][0].extra["id"] == "uuid-2"
    empty = {"result": [{"category": "pagination", "data": {"pages": 1}}]}
    assert search_pages(Kuper(), lambda req: httpx.Response(200, json=empty), board=HOST) == [[]]
    assert Kuper().tasks(SearchConfig())[0].board == HOST
