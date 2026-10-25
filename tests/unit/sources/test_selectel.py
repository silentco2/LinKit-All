from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.selectel import LIST, Selectel


def ok(text: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda req: httpx.Response(404 if req.url.path == "/robots.txt" else 200, text=text)


def test_search_lists_every_vacancy(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    html = load_fixture("selectel/selectel_list.html")
    pages = search_pages(Selectel(), ok(html), calls=calls)
    assert LIST in calls and len(pages) == 1 and len(pages[0]) == 27
    job = pages[0][0]
    assert job.title == "BI-аналитик" and job.company == "Selectel"
    assert job.url == "https://selectel.ru/careers/all/vacancy/1951/"
    assert job.location == "Санкт-Петербург" and job.ats == "selectel"
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-10-13T08:13:17.564387"
    assert job.extra["id"] == "1951"
    assert search_pages(Selectel(), ok(html), start_page=1) == []


def test_fetch_details_reads_the_body(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    html = load_fixture("selectel/selectel_vacancy.html")
    stub = JobStub(
        source="selectel",
        url="https://selectel.ru/careers/all/vacancy/1772/",
        title="t",
        company="c",
    )
    out = fetch_details(Selectel(), ok(html), stub)
    assert "<" not in out.description and "Selectel мы строим" in out.description
    # A page without a vacancy payload leaves the stub as it was.
    same = fetch_details(Selectel(), ok("<html></html>"), stub)
    assert same.description == ""


def test_kind_and_task() -> None:
    assert [t.source for t in Selectel().tasks(SearchConfig())] == ["selectel"]
    assert Selectel().kind == "company" and not Selectel().is_enabled(SearchConfig())
