from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.ozon import Ozon


def test_external_vacancies_only(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(
        Ozon(), lambda req: httpx.Response(200, json=load_fixture("ozon/list.json"))
    )
    assert len(pages) == 1 and len(pages[0]) == 2  # the internal vacancy is dropped
    job = pages[0][0]
    assert job.title == "Associate — M&A and Corporate Development"
    assert job.url == "https://career.ozon.ru/vacancy/136849808/" and job.company == "Ozon"
    assert job.location == "Москва" and job.remote == "hybrid" and job.ats == "ozon"
    assert pages[0][1].remote == "remote"  # "Удалённо" among its formats
    assert job.extra["ozon_id"] == 136849808


def test_paging(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        data = load_fixture("ozon/list.json")
        data["meta"]["totalPages"] = 2
        return httpx.Response(200, json=data)

    assert len(search_pages(Ozon(), handler)) == 2
    assert len(search_pages(Ozon(), handler, start_page=1)) == 1


def test_details(fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]) -> None:
    stub = JobStub(
        source="ozon", url="https://career.ozon.ru/vacancy/136849808/", title="t", company="c"
    )
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=load_fixture("ozon/detail.json"))

    got = fetch_details(Ozon(), handler, stub)
    assert seen == ["/vacancy/136849808"] and "<" not in got.description
    assert "Building and maintaining a pipeline" in got.description
    assert fetch_details(Ozon(), lambda req: httpx.Response(404), stub).description == ""
