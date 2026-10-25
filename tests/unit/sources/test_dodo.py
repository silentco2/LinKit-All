from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.dodo import Dodo


def handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/v1/vacancies":
            return httpx.Response(200, json=load_fixture("dodo/list.json"))
        if req.url.path == "/api/v1/pages/vacancy/7805":
            return httpx.Response(200, json=load_fixture("dodo/detail_7805.json"))
        return httpx.Response(404)

    return handle


def test_groups_are_flattened(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Dodo(), handler(load_fixture))
    assert len(pages) == 1 and len(pages[0]) == 3
    chef, backend, nobrand = pages[0]
    assert chef.title == "Brand Chef" and chef.company == "Dodo Pizza"
    assert chef.url == "https://dodoteam.ru/vacancy/7805" and chef.location == "Дубай"
    assert chef.remote == "hybrid" and chef.extra == {"id": "7805"} and chef.posted_at is None
    assert backend.company == "Dodo Engineering" and backend.remote == "remote"  # renamed brand
    assert nobrand.company == "Dodo" and nobrand.remote is None  # no brand: "Dodo"
    assert search_pages(Dodo(), handler(load_fixture), start_page=1) == []


def test_fetch_details_keeps_body_blocks_only(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="dodo", url="https://dodoteam.ru/vacancy/7805", title="t", company="Dodo Pizza"
    )
    text = fetch_details(Dodo(), handler(load_fixture), stub).description
    for want in ("Lead the kitchen.", "5 years", "cook", "relocation"):
        assert want in text
    assert "x.png" not in text and "image_url" not in text
