from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import avito
from linkit_all.sources.companies.avito import Avito


def handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    files = {
        "/sitemap.xml": "avito/sitemap.xml",
        "/sitemap-iblock-2.xml": "avito/sitemap_vacancies.xml",
        "/sitemap-iblock-9.xml": "avito/sitemap_other.xml",
        "/vacancies/prodazhi/19548/": "avito/vacancy_remote.html",
        "/vacancies/razrabotka/17810/": "avito/vacancy_office.html",
    }

    def handle(req: httpx.Request) -> httpx.Response:
        name = files.get(req.url.path)
        if req.url.path == "/robots.txt" or not name:
            return httpx.Response(404)  # includes the broken sub-sitemap
        return httpx.Response(200, text=load_fixture(name))

    return handle


def test_sitemap_then_vacancies(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Avito(), handler(load_fixture), calls=calls)
    assert len(pages) == 1
    # 19548 sits under two categories (fetched once) and the category page has no id
    assert sum(u.endswith("/19548/") for u in calls) == 1
    by_id = {s.extra["id"]: s for s in pages[0]}
    assert set(by_id) == {"17810", "19548"}
    remote, office = by_id["19548"], by_id["17810"]
    assert remote.title == "Менеджер по работе с клиентами" and remote.company == "Avito"  # noqa: RUF001
    assert remote.url == "https://career.avito.com/vacancies/prodazhi/19548/"
    assert remote.location == "Удалённая работа" and remote.remote == "remote"  # page title city
    assert "Обязанности" in remote.description and "alert" not in remote.description
    assert remote.posted_at is not None and remote.posted_at.isoformat() == "2026-05-15T13:24:19"
    assert office.location == "Москва" and office.remote is None  # no title city: the JSON-LD one
    assert office.source == "avito" and office.ats == "avito"


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(avito, "CHUNK", 1)
    assert [len(p) for p in search_pages(Avito(), handler(load_fixture))] == [1, 1]
    resumed = search_pages(Avito(), handler(load_fixture), start_page=1)
    assert [s.extra["id"] for p in resumed for s in p] == [
        "17810"
    ]  # sorted by URL: prodazhi, razrabotka


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="avito",
        url="https://career.avito.com/vacancies/razrabotka/17810/",
        title="t",
        company="Avito",
    )
    assert "Пишем сервисы" in fetch_details(Avito(), handler(load_fixture), stub).description
