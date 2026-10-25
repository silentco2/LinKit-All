from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.domclick import Domclick, work_mode


def handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handle(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/api/v1/vacancy/":
            return httpx.Response(200, json=load_fixture("domclick/list.json"))
        if path.startswith("/api/v1/vacancy/detail/"):
            slug = path.removeprefix("/api/v1/vacancy/detail/").strip("/")
            return httpx.Response(200, json=load_fixture(f"domclick/detail_{slug}.json"))
        return httpx.Response(404)

    return handle


def test_list(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Domclick(), handler(load_fixture))
    assert len(pages) == 1
    marketing, backend = pages[0]
    assert marketing.title == "Marketing Lead" and marketing.company == "DomClick"
    assert marketing.url == "https://career.domclick.ru/vacancy/marketing-84"
    assert marketing.location == "Москва" and marketing.remote == "hybrid"
    assert backend.remote == "remote" and backend.extra == {"id": "backend-85"}
    assert marketing.posted_at is None and marketing.source == "domclick"
    assert search_pages(Domclick(), handler(load_fixture), start_page=1) == []


def test_fetch_details_prefers_branded_copy(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    def stub(slug: str) -> JobStub:
        return JobStub(
            source="domclick",
            url=f"https://career.domclick.ru/vacancy/{slug}",
            title="t",
            company="DomClick",
        )

    branded = fetch_details(Domclick(), handler(load_fixture), stub("marketing-84")).description
    assert branded == "Branded marketing copy."  # the <style> block is dropped
    plain = fetch_details(Domclick(), handler(load_fixture), stub("backend-85")).description
    assert plain == "Plain backend copy."


def test_work_mode() -> None:
    assert work_mode(["ON_SITE"], "") == "onsite"
    assert work_mode([], "Удалённо") == "remote"
    assert work_mode([], "Москва") is None
