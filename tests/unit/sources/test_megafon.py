# ruff: noqa: RUF001
from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.megafon import Megafon

FILES = {
    ("2374", "1"): "vacancies_remote",
    ("2375", "1"): "vacancies_all_cities",
    ("1", "1"): "vacancies_moscow_p1",
    ("1", "2"): "vacancies_moscow_p2",
    ("16", "1"): "vacancies_volgograd",
}


def handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/cities/available"):
            return httpx.Response(200, json=load_fixture("megafon/cities.json"))
        if req.url.path == "/api/v1/vacancies":
            key = (req.url.params["cities"], req.url.params["page"])
            return httpx.Response(200, json=load_fixture(f"megafon/{FILES[key]}.json"))
        if req.url.path == "/api/v1/vacancies/android-razrabotchik-4763":
            assert req.url.params["cityId"] == "2374"
            return httpx.Response(200, json=load_fixture("megafon/detail_4763.json"))
        return httpx.Response(404)

    return handle


def test_walks_city_by_city_and_merges(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Megafon(), handler(load_fixture))
    assert len(pages) == 4  # one page of stubs per city
    jobs = {j.extra["megafon_id"]: j for p in pages for j in p}
    assert (
        len(jobs) == sum(len(p) for p in pages) == 13
    )  # the Moscow/Volgograd overlap is kept once

    android = jobs[4763]
    assert (
        android.url
        == "https://job.megafon.ru/vacancy/udalennyj-format/it-reshenia/android-razrabotchik-4763"
    )
    assert android.title == "Android-разработчик" and android.company == "МегаТех"
    assert android.remote == "remote" and android.location == "Россия"
    assert android.posted_at is not None and android.posted_at.year == 2026
    assert jobs[4794].remote == "hybrid"  # tag hybrid_shift
    assert jobs[4801].location == "Москва" and jobs[4801].remote is None
    assert jobs[3284].location == "Россия"  # listed under "all cities"
    assert jobs[3284].company == "МегаФон Ритейл"


def test_resume_skips_cities(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Megafon(), handler(load_fixture), start_page=3)
    assert [j.extra["megafon_id"] for j in pages[0]] == [3876, 3875]


def test_details(fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]) -> None:
    url = "https://job.megafon.ru/vacancy/udalennyj-format/it-reshenia/android-razrabotchik-4763"
    stub = JobStub(source="megafon", url=url, title="t", company="c")  # the enrich stage's stub
    got = fetch_details(Megafon(), handler(load_fixture), stub)
    assert got.description.startswith("Обязанности\n")
    assert "Требования\n" in got.description and "Разрабатывать новые функции" in got.description
    unknown = stub.model_copy(update={"url": url.replace("udalennyj-format", "nowhere")})
    assert fetch_details(Megafon(), handler(load_fixture), unknown).description == ""


def test_task() -> None:
    assert Megafon().tasks(SearchConfig())[0].key == "megafon:careers"
