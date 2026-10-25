from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import kaspi
from linkit_all.sources.companies.kaspi import HOST, Kaspi, salary

JAVA = "middle-java-developer"
DBA = "junior-database-administrator-postgresql"


def handler_for(
    load_fixture: Callable[[str], Any], missing: str = ""
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/sitemap/vacancies.xml":
            return httpx.Response(200, text=load_fixture("kaspi/sitemap.xml"))
        slug = path.removeprefix("/vacancy/")
        if path.startswith("/vacancy/") and slug != missing:
            return httpx.Response(200, text=load_fixture(f"kaspi/{slug}.html"))
        return httpx.Response(404)

    return handler


def test_sitemap_then_vacancy_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Kaspi(), handler_for(load_fixture), board=HOST)
    assert len(pages) == 1 and len(pages[0]) == 4
    by_id = {s.extra["id"]: s for s in pages[0]}
    java = by_id[JAVA]
    assert java.title == "Middle/Senior Java Developer Kaspi Shop"
    assert java.company == "Kaspi.kz" and java.url == f"https://{HOST}/vacancy/{JAVA}"
    assert java.location == "Алматы"  # the "(Головной офис)" note names no place
    assert (java.salary_min, java.salary_max) == (800000, None)
    assert java.salary_currency == "KZT" and java.salary_interval == "month"
    assert java.posted_at is not None and java.posted_at.isoformat().startswith(
        "2026-01-23T12:24:58"
    )
    assert "Описание" in java.description and "<" not in java.description
    assert java.extra["schedule"][0] == "Гибкий график" and java.ats == "kaspi"
    dba, gid = by_id[DBA], by_id["kaspi-gid"]
    assert dba.salary_min is None and dba.salary_currency is None
    assert gid.location == "Алматы, Астана, Жезказган, Усть-Каменогорск"


def test_gone_page_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(kaspi, "CHUNK", 2)
    pages = search_pages(Kaspi(), handler_for(load_fixture, missing="kaspi-gid"), board=HOST)
    assert [len(p) for p in pages] == [1, 2]  # the 404 page is left out of the first chunk
    resumed = search_pages(Kaspi(), handler_for(load_fixture), board=HOST, start_page=1)
    assert [s.extra["id"] for s in resumed[0]] == [JAVA, "menedzher-po-privlecheniyu-partnerov"]


def test_salary_label() -> None:
    assert salary("от 800 000 тенге") == (800000, None)
    assert salary("до 1.500.000 ₸") == (None, 1500000)
    assert salary("300 000") == (300000, 300000)
    assert salary("200 000 - 300 000 тенге") == (None, None)  # a range: not guessed
    assert salary("") == (None, None) and salary("договорная") == (None, None)


def test_task() -> None:
    assert Kaspi().tasks(SearchConfig())[0].board == HOST
