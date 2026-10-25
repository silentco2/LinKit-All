from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.magnit import Magnit


def test_list_stubs(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(
        Magnit(), lambda req: httpx.Response(200, json=load_fixture("magnit/list.json"))
    )
    assert len(pages) == 1 and len(pages[0]) == 3
    job = pages[0][0]
    assert job.title == "Разработчик Fullstack Senior (Python, Vue.js)"
    assert job.url == "https://magnit.tech/vacancies/2886" and job.apply_url == job.url
    assert job.company == "Magnit Tech" and job.source == job.ats == "magnit"
    assert job.location == "Россия; Москва и Краснодар (гибрид/офис), другие города - удаленно"
    assert job.remote == "remote"  # the broadest arrangement the label offers
    assert job.extra["skills"] == ["Python", "Vue.js"]
    assert pages[0][1].location.startswith("Москва")  # location is null: only the work format


def test_paging_follows_has_more_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        data = load_fixture("magnit/list.json")
        if req.url.params["page"] == "1":
            data = {**data, "meta": {"has_more_pages": True}, "results": data["results"][:1]}
        else:
            data = {**data, "results": data["results"][1:]}
        return httpx.Response(200, json=data)

    calls: list[str] = []
    pages = search_pages(Magnit(), handler, calls=calls)
    assert [len(p) for p in pages] == [1, 2] and len(calls) == 2
    assert search_pages(Magnit(), handler, start_page=1)[0][0].url.endswith("/2921")


def test_details(fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]) -> None:
    stub = JobStub(
        source="magnit", url="https://magnit.tech/vacancies/2886", title="t", company="c"
    )
    got = fetch_details(
        Magnit(), lambda req: httpx.Response(200, json=load_fixture("magnit/vacancy.json")), stub
    )
    assert "Стек технологий: Postgres" in got.description
    assert "Задачи\n" in got.description and "Требования\n" in got.description

    closed = load_fixture("magnit/vacancy.json")
    closed["results"]["status"] = "closed"
    assert (
        fetch_details(Magnit(), lambda req: httpx.Response(200, json=closed), stub).description
        == ""
    )
    assert fetch_details(Magnit(), lambda req: httpx.Response(404), stub).description == ""


def test_task() -> None:
    assert Magnit().tasks(SearchConfig())[0].key == "magnit:careers"
