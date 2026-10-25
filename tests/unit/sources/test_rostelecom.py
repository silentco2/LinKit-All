# ruff: noqa: RUF001
from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.rostelecom import Rostelecom


def handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda req: httpx.Response(
        200, json=load_fixture(f"rostelecom/vacancies_p{req.url.params['page']}.json")
    )


def test_pages_from_zero(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Rostelecom(), handler(load_fixture), calls=calls)
    assert [len(p) for p in pages] == [3, 2, 1] and len(calls) == 3
    job = pages[0][0]
    assert job.title == "Машинист экскаватора" and job.company == "Rostelecom"
    assert job.url == "https://job.rt.ru/vacancy/14629" and job.location == "Пушкино г"
    assert job.salary_min == 70190 and job.salary_max == 87738
    assert job.salary_currency == "RUB" and job.salary_interval == "month"
    assert job.description.startswith("Чем предстоит заниматься\n")
    assert pages[0][1].salary_max == 83700  # a lone lower bound fills both
    assert pages[1][1].salary_min is None  # no salary at all


def test_hybrid_tag_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    hybrid = search_pages(Rostelecom(), handler(load_fixture), start_page=0)[0][2]
    assert hybrid.title == "Инженер" and hybrid.remote is None  # tag 6 is not the hybrid tag
    data = load_fixture("rostelecom/vacancies_p0.json")
    data["vacancies"][0]["tags"] = [{"id": 11, "name": "Гибрид"}]
    pages = search_pages(
        Rostelecom(), lambda req: httpx.Response(200, json={**data, "totalPages": 1})
    )
    assert pages[0][0].remote == "hybrid"
    assert [len(p) for p in search_pages(Rostelecom(), handler(load_fixture), start_page=2)] == [1]
