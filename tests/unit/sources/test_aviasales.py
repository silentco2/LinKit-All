from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.aviasales import Aviasales


def handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/vacancies":
            return httpx.Response(200, json=load_fixture("aviasales/list.json"))
        if req.url.path == "/about/vacancies/111":
            assert req.url.params["__loader"] == "about/vacancies/(id)/page"
            return httpx.Response(200, json=load_fixture("aviasales/detail_111.json"))
        return httpx.Response(404)

    return handle


def test_list(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Aviasales(), handler(load_fixture))
    assert len(pages) == 1
    remote, office = pages[0]
    assert remote.title == "Support Specialist" and remote.company == "Aviasales"
    assert remote.url == "https://www.aviasales.ru/about/vacancies/111"
    assert remote.location == "Удалённо" and remote.remote == "remote"
    assert office.location == "Москва" and office.remote is None
    assert remote.extra == {"id": "111"} and remote.description == ""
    assert remote.posted_at is None and remote.source == "aviasales"
    assert search_pages(Aviasales(), handler(load_fixture), start_page=1) == []


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="aviasales",
        url="https://www.aviasales.ru/about/vacancies/111",
        title="t",
        company="Aviasales",
    )
    text = fetch_details(Aviasales(), handler(load_fixture), stub).description
    assert "About Aviasales." in text and "help clients" in text and "flexible schedule" in text
    assert "alert" not in text
