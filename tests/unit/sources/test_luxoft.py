from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.luxoft import Luxoft
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
        if path == "/jobs":
            page = req.url.params.get("page", "1")
            assert req.url.params["perPage"] == "60"
            # the first page has no page parameter; past the last one the site shows no jobs
            assert page != "1" or "page" not in req.url.params
            text = {"1": "listing_1", "2": "listing_2"}.get(page)
            return httpx.Response(
                200, text=load_fixture(f"luxoft/{text}.html") if text else "<html/>"
            )
        num = path.rsplit("-", 1)[-1]
        if num in ("25262", "25301"):
            return httpx.Response(200, text=load_fixture(f"luxoft/detail_{num}.html"))
        return httpx.Response(404)  # 25400 is gone

    return handler


def test_paged_listing_then_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Luxoft(), make_handler(load_fixture), board="career.luxoft.com")
    assert [[j.title for j in p] for p in pages] == [
        ["Senior Java Developer", "Data Engineer (Remote)"],
        [],  # QA Engineer is gone; the repeated Java link on page 2 is not fetched again
    ]
    a, b = pages[0]
    assert a.url == "https://career.luxoft.com/jobs/senior-java-developer-25262"
    assert a.company == "Luxoft" and a.location == "Wroclaw, Poland" and a.ats is None
    assert a.description == "Build banking systems." and a.extra == {
        "id": "25262",
        "employment": None,
        "valid_through": None,
    }
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-09-15T10:30:00"
    assert b.posted_at is None  # a future datePosted is a placeholder
    assert b.description == "Move data."


def test_resume_from_a_later_listing_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Luxoft(), make_handler(load_fixture), board="career.luxoft.com", start_page=1, calls=calls
    )
    assert [len(p) for p in pages] == [1]  # Java again (seen only within a run) and QA is gone
    assert not any("/jobs?perPage=60" in c and "page=" not in c for c in calls)


def test_robots_refusal_raises(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    from linkit_all.sources.careers import Unsupported

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="User-agent: *\nDisallow: /jobs")

    with pytest.raises(Unsupported):
        search_pages(Luxoft(), handler, board="career.luxoft.com")


def test_task_and_registration() -> None:
    tasks = Luxoft().tasks(SearchConfig())
    assert len(tasks) == 1 and tasks[0].source == "luxoft" and tasks[0].board == "career.luxoft.com"
    found = registry()["luxoft"]
    assert found.kind == "company" and not found.is_enabled(SearchConfig())
