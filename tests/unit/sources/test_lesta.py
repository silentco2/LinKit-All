from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.lesta import HOST, Lesta


def listing(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json=load_fixture(f"lesta/lesta_filters_{req.url.params['offset']}.json")
        )

    return handler


def test_listing_pages_by_offset_until_total(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Lesta(), listing(load_fixture), board=HOST, calls=calls)
    assert [c.rsplit("=", 1)[1] for c in calls] == ["0", "15", "30"]  # 15 + 15 + 8 = 38
    assert [len(p) for p in pages] == [15, 15, 8]
    job = pages[2][0]
    assert job.title == "Monitoring Engineer" and job.company == "Lesta Games"
    assert job.url == f"https://{HOST}/vacancy/monitoring-engineer/569"
    assert job.location == "Минск без графика работы" and job.extra["id"] == "569"
    assert job.description == "" and job.ats == "lesta"
    assert job.extra["experience"] == ["От 1 года до 3 лет", "От 3 до 6 лет"]
    calls.clear()
    search_pages(Lesta(), listing(load_fixture), board=HOST, start_page=2, calls=calls)
    assert [c.rsplit("=", 1)[1] for c in calls] == ["30"]


def test_details_join_the_vacancy_blocks_without_the_skill_tags(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="lesta",
        url=f"https://{HOST}/vacancy/senior-backend-engineer/575",
        title="Senior Backend Engineer",
        company="Lesta Games",
    )
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, text=load_fixture("lesta/lesta_vacancy.html"))

    full = fetch_details(Lesta(), handler, stub)
    assert "/vacancy/senior-backend-engineer/575" in seen
    assert "Леста Игры" in full.description and "Что мы предлагаем" in full.description
    assert "Senior Backend Engineer" in full.description
    assert "Навыки" not in full.description  # the skills block repeats the tags
    assert "<div" not in full.description and "<p>" not in full.description


def test_task_and_kind() -> None:
    assert Lesta().tasks(SearchConfig())[0].board == HOST
    assert Lesta().kind == "company"
