from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.boards import builtin
from linkit_all.sources.boards.builtin import BuiltIn, parse_cards

WASABI = "https://builtin.com/job/architect-object-storage-database-systems/11687409"
PWC = "https://builtin.com/job/strategy-operations-strategy-consultant-senior-associate/11691513"


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtin, "INTERVAL", 0.001)
    monkeypatch.setattr("linkit_all.sources.http.Http._limiter", _free)


def _free(self: Any, host: str) -> Any:
    from aiolimiter import AsyncLimiter

    return AsyncLimiter(1000, 1)


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    details = {
        "/job/architect-object-storage-database-systems/11687409": "detail_remote.html",
        "/job/strategy-operations-strategy-consultant-senior-associate/11691513": "detail_multi_location.html",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/jobs/dev-engineering" and "page" not in req.url.params:
            return httpx.Response(200, text=load_fixture("builtin/list.html"))
        if req.url.path.startswith("/jobs/"):
            return httpx.Response(200, text=load_fixture("builtin/list_past_end.html"))
        if req.url.path in details:
            return httpx.Response(200, text=load_fixture(f"builtin/{details[req.url.path]}"))
        return httpx.Response(404)

    return handler


def test_parse_cards(load_fixture: Callable[[str], Any]) -> None:
    cards = parse_cards(load_fixture("builtin/list.html"))
    assert [c.id for c in cards] == ["11691620", "11691513", "11687409", "11691412"]
    assert cards[0].company == "Xero" and cards[0].mode == "hybrid"
    assert cards[2].mode == "remote" and cards[3].mode is None
    assert parse_cards(load_fixture("builtin/list_past_end.html")) == []


def test_search_walks_categories_and_stops_at_the_end(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(BuiltIn(), _serve(load_fixture), calls=calls)
    assert len(pages) == 1 and len(pages[0]) == 4
    job = pages[0][2]
    assert job.url == WASABI and job.company == "Wasabi Technologies" and job.remote == "remote"
    assert job.title.startswith("Architect") and job.extra["id"] == "11687409"
    assert job.description == ""  # the body comes with fetch_details
    # dev-engineering has two pages (data, then the empty one), every other family one empty page
    assert sum("/jobs/dev-engineering" in c for c in calls) == 2
    listings = [c for c in calls if "/jobs/" in c]
    assert all("daysSinceUpdated=1" in c for c in listings)
    assert len(listings) == 2 + len(builtin.CATEGORIES) - 1


def test_limit_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(BuiltIn(), _serve(load_fixture), limit=2)
    assert [len(p) for p in pages] == [2]
    assert search_pages(BuiltIn(), _serve(load_fixture), start_page=1) == []


def test_tasks() -> None:
    cfg = SearchConfig.model_validate({"search": {"queries": ["a", "b", "c"]}})
    assert [t.key for t in BuiltIn().tasks(cfg)] == ["builtin:feed"]


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="builtin", url=WASABI, title="Architect", company="Wasabi", remote="remote"
    )
    got = fetch_details(BuiltIn(), _serve(load_fixture), stub)
    assert got.company == "Wasabi Technologies" and got.title == "Architect"
    assert "Wasabi" in got.description and "<" not in got.description
    assert got.posted_at is not None and got.posted_at.date().isoformat() == "2026-10-14"
    assert (got.salary_min, got.salary_max, got.salary_currency) == (200000, 250000, "USD")
    assert got.salary_interval == "year" and got.remote == "remote"

    multi = fetch_details(
        BuiltIn(), _serve(load_fixture), stub.model_copy(update={"url": PWC, "remote": None})
    )
    assert multi.location.count(";") >= 1 and "Dallas" in multi.location


def test_nonsense_hourly_wage_is_dropped(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    page = load_fixture("builtin/detail_hourly_error.html")
    stub = JobStub(source="builtin", url=WASABI, title="Intern", company="PwC")
    got = fetch_details(BuiltIn(), lambda req: httpx.Response(200, text=page), stub)
    assert got.salary_min is None and got.salary_currency is None and got.description


def test_gone_posting_keeps_the_stub(fetch_details: Callable[..., JobStub]) -> None:
    stub = JobStub(source="builtin", url=WASABI, title="Architect", company="Wasabi")
    assert fetch_details(BuiltIn(), lambda req: httpx.Response(404), stub) == stub
