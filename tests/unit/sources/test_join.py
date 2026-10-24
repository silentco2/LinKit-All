from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.join import Join, plain
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))
    yield


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/companies/justhiringde":
            return httpx.Response(200, text=load_fixture("join/company_page.html"))
        if path == "/api/public/companies/167291/jobs":
            assert req.url.params["pageSize"] == "5"  # larger pages are rejected with 422
            return httpx.Response(
                200, json=load_fixture(f"join/list_page{req.url.params['page']}.json")
            )
        if path == "/api/public/jobs/16291946":  # gone between list and detail
            return httpx.Response(404, json={"error": {"msg": "Entity not found"}})
        if path.startswith("/api/public/jobs/"):
            detail = load_fixture("join/detail_16291944.json")
            return httpx.Response(200, json=detail)
        return httpx.Response(404)

    return handler


def test_pages_and_details(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Join(), make_handler(load_fixture), board="167291")
    assert [[j.title for j in p] for p in pages] == [
        ["CRO Manager", "Remote SDR"],  # the third posting vanished: dropped
        ["Account Executive"],
    ]
    a, b = pages[0]
    assert a.url == "https://join.com/companies/justhiringde/16291944-cro-manager"
    assert a.company == "Justhiringde" and a.location == "Berlin, Germany" and a.remote == "onsite"
    assert a.description == "Intro line.\n\n- Own the funnel\n- Ship fast"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-06-11T11:51:32.030000"
    assert a.ats == "join" and a.extra == {"board": "167291", "id": "16291944"}
    assert b.remote == "remote" and b.location == ""
    assert pages[1][0].remote == "hybrid"


def test_resume_from_a_later_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Join(), make_handler(load_fixture), board="167291", start_page=1, calls=calls
    )
    assert [j.title for p in pages for j in p] == ["Account Executive"]
    assert not any("page=1" in c for c in calls)


def test_slug_board_is_resolved_on_the_company_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Join(), make_handler(load_fixture), board="justhiringde", calls=calls)
    assert "https://join.com/companies/justhiringde" in calls
    assert len(pages) == 2 and pages[0][0].extra["board"] == "justhiringde"


def test_unknown_slug_is_an_error(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<html>no id here</html>")

    with pytest.raises(ValueError, match="company id"):
        search_pages(Join(), handler, board="nobody")


def test_fetch_details_from_url(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="join",
        url="https://join.com/companies/justhiringde/16291944-cro-manager",
        title="t",
        company="c",
    )
    assert fetch_details(Join(), make_handler(load_fixture), stub).description.endswith("Ship fast")


def test_plain_markdown() -> None:
    assert plain("**Bold** and __more__\n* a\n+ b\n  - c") == "Bold and more\n- a\n- b\n- c"


def test_url_patterns() -> None:
    assert detect("https://join.com/companies/justhiringde") == ("join", "justhiringde")
    assert detect("https://join.com/companies/justhiringde/16291944-cro-manager") == (
        "join",
        "justhiringde",
    )
    assert detect("join:167291") == ("join", "167291")
