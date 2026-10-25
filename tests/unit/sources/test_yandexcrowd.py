from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.yandexcrowd import PAGE, YandexCrowd, parse_page, work_mode


def ok(text: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda req: httpx.Response(404 if req.url.path == "/robots.txt" else 200, text=text)


def test_search_keeps_available_vacancies(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    html = load_fixture("yandexcrowd/vacancies.html")
    calls: list[str] = []
    pages = search_pages(YandexCrowd(), ok(html), calls=calls)
    assert PAGE in calls and len(pages) == 1
    remote, local = pages[0]  # the third vacancy is taken down
    assert remote.title == "Аналитик по соцсетям" and remote.company == "Yandex Crowd"
    assert remote.url == "https://crowd.yandex.ru/back_office/analytics/analitik_smm"
    assert remote.extra["id"] == "back_office/analytics/analitik_smm"
    assert remote.remote == "remote" and remote.description == "Осваивайте профессию"
    assert local.remote == "onsite" and local.ats == "yandexcrowd"


def test_unreadable_pages_and_helpers() -> None:
    assert parse_page("<html><body>no data</body></html>") == []
    assert parse_page('<script id="data" type="application/json">not json</script>') == []
    assert [work_mode(x) for x in ("удалённо", "локально", "?", None)] == [
        "remote",
        "onsite",
        None,
        None,
    ]
    assert YandexCrowd().tasks(SearchConfig())[0].source == "yandexcrowd"
