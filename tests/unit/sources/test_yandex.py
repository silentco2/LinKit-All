from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.yandex import Yandex, cursor_of


def serve(load_fixture: Callable[[str], Any], calls: list[str]) -> Callable[..., httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/111") or path.endswith("/222"):
            return httpx.Response(200, json=load_fixture(f"yandex/detail_{path[-3:]}.json"))
        if path.endswith("/900") or path.endswith("/901"):
            raise AssertionError("redirects and hiring events must not be fetched")
        page = 2 if req.url.params.get("cursor") == "ABC" else 1
        return httpx.Response(200, json=load_fixture(f"yandex/list_p{page}.json"))

    return handler


def test_search_follows_the_cursor_and_drops_non_vacancies(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Yandex(), serve(load_fixture, calls), board="ru", calls=calls)
    assert [len(p) for p in pages] == [1, 1]
    data, backend = pages[0][0], pages[1][0]
    assert data.title == "Data Engineer" and data.company == "Yandex" and data.ats == "yandex"
    assert data.url == "https://yandex.ru/jobs/vacancies/data-111"
    assert data.location == "Москва, Санкт-Петербург" and data.remote is None
    assert "data platform" in data.description and "Design pipelines" in data.description
    assert "Flexible hours" in data.description and "<" not in data.description
    assert data.posted_at is not None and data.posted_at.year == 2026 and data.posted_at.month == 6
    assert data.extra == {"id": "111", "host": "ru"}
    assert backend.remote == "remote" and backend.url.endswith("/backend-222")
    assert calls[0] == "https://yandex.ru/jobs/api/publications"
    assert any("cursor=ABC" in c for c in calls)


def test_resume_skips_earlier_pages_without_details(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Yandex(), serve(load_fixture, calls), board="ru", start_page=1, calls=calls
    )
    assert [s.title for p in pages for s in p] == ["Backend Developer"]
    assert not any(c.endswith("/111") for c in calls)  # page 1's detail was not requested


def test_board_picks_the_host_and_a_failed_detail_skips_the_vacancy(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/111"):
            return httpx.Response(404)
        return serve(load_fixture, [])(req)

    pages = search_pages(Yandex(), handler, board="com")
    assert [s.title for p in pages for s in p] == ["Backend Developer"]
    assert pages[-1][0].url == "https://yandex.com/jobs/vacancies/backend-222"


def test_runaway_cursor_ends(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    n = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal n
        n += 1
        return httpx.Response(200, json={"results": [], "next": "http://h/?cursor=LOOP"})

    assert [s for p in search_pages(Yandex(), handler, board="ru") for s in p] == []
    assert n == 2  # the bare page, then the LOOP page whose next cursor repeats


def test_cursor_and_task() -> None:
    assert cursor_of("http://x/_api/?cursor=ABC&page_size=20") == "ABC"
    assert cursor_of(None) == "" and cursor_of("http://x/?page=2") == ""
    task = Yandex().tasks(SearchConfig())[0]
    assert (task.board, task.limit) == ("ru", 200)
