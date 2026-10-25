from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.x5 import X5, parse_item


def test_search_pages_to_the_last_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        page = req.url.params["page"]
        seen.append(f"{page}/{req.url.params['page_size']}")
        return httpx.Response(200, json=load_fixture(f"x5/list_p{page}.json"))

    pages = search_pages(X5(), handler)
    assert seen == ["1/100", "2/100"] and [len(p) for p in pages] == [3, 2]
    go = pages[0][0]
    assert go.title == "Senior Go developer" and go.company == "X5 Tech"
    assert go.url == "https://rabota.x5.ru/vacancies/76dc9436-816f-4583-98a3-c04ac13b32e7"
    assert go.location == "Москва" and go.remote == "onsite" and go.ats == "x5"
    assert go.posted_at is not None and go.posted_at.isoformat() == "2026-09-07T11:05:09.118552"
    assert go.salary_min is None and go.description == ""
    assert pages[0][1].remote == "hybrid" and pages[0][1].company == "Чижик"
    assert pages[0][2].location == "г. Нижний Новгород, ул. Долгополова, д. 77"  # no city: address  # noqa: RUF001
    assert pages[1][0].remote == "remote"
    seen.clear()
    search_pages(X5(), handler, start_page=1)
    assert seen == ["2/100"]


def test_salary_and_company_fallback() -> None:
    exact = parse_item({"id": "a", "name": "n", "salary": 90000})
    assert exact is not None and exact.company == "X5 Group"
    assert (exact.salary_min, exact.salary_max) == (90000, 90000)
    assert (exact.salary_currency, exact.salary_interval) == ("RUB", "month")
    span = parse_item({"id": "b", "name": "n", "salary_min": 50000, "salary_max": 70000})
    assert span is not None and (span.salary_min, span.salary_max) == (50000, 70000)
    assert parse_item({"id": "c"}) is None


def test_fetch_details_assembles_the_body(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    data = load_fixture("x5/detail_76dc9436-816f-4583-98a3-c04ac13b32e7.json")
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, json=data)

    stub = JobStub(
        source="x5",
        url="https://rabota.x5.ru/vacancies/76dc9436-816f-4583-98a3-c04ac13b32e7",
        title="t",
        company="X5 Tech",
    )
    out = fetch_details(X5(), handler, stub)
    assert calls == [
        "https://rabota.x5.ru/vacancy/api/v1/public/vacancies/76dc9436-816f-4583-98a3-c04ac13b32e7"
    ]
    assert out.description.startswith("Особенности\n- Удалённо или гибрид")
    assert "Условия" in out.description and "Цифровая академия" in out.description


def test_kind_and_task() -> None:
    assert [t.board for t in X5().tasks(SearchConfig())] == ["rabota.x5.ru"]
    assert X5().kind == "company" and not X5().is_enabled(SearchConfig())
