from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.halyk import HOST, Halyk, cards, identity


def handler_for(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        pages = {
            "/about/career/vacancies": "halyk/list.html",
            "/about/career/vacancies-inner/9": "halyk/red-team.html",
            "/about/career/vacancies-inner/1": "halyk/golang.html",
        }
        return (
            httpx.Response(200, text=load_fixture(pages[path]))
            if path in pages
            else httpx.Response(404)
        )

    return handler


def test_cards_resolve_relative_links(load_fixture: Callable[[str], Any]) -> None:
    got = cards(load_fixture("halyk/list.html"), f"https://{HOST}/about/career/vacancies")
    assert got == [
        (f"https://{HOST}/about/career/vacancies-inner/9", "Red Team Expert", "Алматы"),
        (f"https://{HOST}/about/career/vacancies-inner/1", "GoLang разработчик", "Астана"),
    ]


def test_search_reads_each_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Halyk(), handler_for(load_fixture), board=HOST)
    red, go = pages[0]
    assert red.title == "Red Team Expert" and red.company == "Halyk Bank"
    assert red.location == "Алматы" and red.url.endswith("/vacancies-inner/9")
    assert "Основные обязанности" in red.description and "Проведение атак" in red.description
    assert "var x" not in red.description  # script bodies are dropped
    assert "Требования" in go.description and go.location == "Астана"
    # the id follows title and city, not the path number
    assert red.extra["id"] == identity("Red Team Expert", "Алматы") != "9"


def test_identity_folds_case_and_whitespace() -> None:
    assert identity("GoLang разработчик", "Алматы") == identity(" golang  разработчик ", "алматы")
    assert identity("GoLang разработчик", "Алматы") != identity("GoLang разработчик", "Астана")


def test_gone_page_is_left_out_and_empty_listing_fails(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    base = handler_for(load_fixture)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if req.url.path.endswith("/9") else base(req)

    pages = search_pages(Halyk(), handler, board=HOST)
    assert [s.title for s in pages[0]] == ["GoLang разработчик"]
    try:
        search_pages(Halyk(), lambda req: httpx.Response(200, text="<html></html>"), board=HOST)
    except ValueError as e:
        assert "markup changed" in str(e)
    else:
        raise AssertionError("an empty listing must fail, not read as no vacancies")
    assert Halyk().tasks(SearchConfig())[0].board == HOST
