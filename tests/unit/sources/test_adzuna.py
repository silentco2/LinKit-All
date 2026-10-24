from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators import adzuna
from linkit_all.sources.aggregators._keyed import DailyBudget
from linkit_all.sources.aggregators.adzuna import Adzuna
from linkit_all.sources.base import JobStub
from linkit_all.sources.careers import Unsupported

KEYS = {"app_id": "myid", "app_key": "mykey"}


def keys(name: str) -> dict[str, str] | None:
    return KEYS if name == "adzuna" else None


def cfg(locations: list[str], queries: list[str] | None = None) -> SearchConfig:
    return SearchConfig.model_validate(
        {"search": {"queries": queries or ["python developer"], "locations": locations}}
    )


def test_no_key_no_tasks() -> None:
    assert Adzuna(keys=lambda n: None).tasks(cfg(["Leeds, UK"])) == []
    assert Adzuna(keys=lambda n: {"app_id": "1"}).tasks(cfg(["Leeds, UK"])) == []
    assert Adzuna().tasks(cfg(["Leeds, UK"])) == []


def test_tasks_map_locations_to_adzuna_countries() -> None:
    tasks = Adzuna(keys=keys).tasks(cfg(["Leeds, UK", "Austin, United States", "Egypt", ""]))
    assert [t.country for t in tasks] == ["gb", "us", "", ""]  # Egypt and "anywhere": no market
    assert tasks[0].query == "python developer" and tasks[0].posted_within_days == 14


def test_search_sends_keys_and_params_and_maps_stubs(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("adzuna/search.json"))

    pages = search_pages(
        Adzuna(keys=keys),
        handler,
        query="python developer",
        location="Leeds, UK",
        country="gb",
        posted_within_days=3,
    )
    (req,) = seen
    assert req.url.path == "/v1/api/jobs/gb/search/1"
    q = req.url.params
    assert (q["app_id"], q["app_key"]) == ("myid", "mykey")
    assert (q["what"], q["where"], q["max_days_old"]) == ("python developer", "Leeds", "3")
    assert (q["results_per_page"], q["sort_by"]) == ("50", "date")
    assert len(pages) == 1 and len(pages[0]) == 2  # the row without a title is dropped
    j, k = pages[0]
    assert (j.title, j.company, j.location) == ("Backend Engineer", "Acme", "Leeds, West Yorkshire")
    assert j.url == "https://www.adzuna.co.uk/jobs/land/ad/4812345678" and j.apply_url == j.url
    assert j.description.startswith("Great role. Build APIs in Python & Go")
    assert (j.salary_min, j.salary_max, j.salary_currency) == (55000.0, 65000.0, "GBP")
    assert j.posted_at is not None and j.ats == "adzuna" and j.extra["id"] == "4812345678"
    assert k.extra["id"] == "4812345679" and k.remote == "remote"  # numeric ids are accepted
    assert k.salary_min is None  # a predicted salary is not the posting's


def test_unsupported_country_and_missing_country(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(Unsupported, match="no market for Egypt"):
        search_pages(Adzuna(keys=keys), boom, query="x", location="Cairo, Egypt")
    with pytest.raises(Unsupported, match="needs a country"):
        search_pages(Adzuna(keys=keys), boom, query="x", location="")


def test_paging_resume_and_limit(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    row = load_fixture("adzuna/search.json")["results"][0]
    full = {
        "results": [
            {**row, "id": str(i), "redirect_url": f"https://a.example/{i}"} for i in range(50)
        ]
    }
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=full if req.url.path.endswith(("/1", "/2", "/3")) else {})

    src = Adzuna(keys=keys)
    pages = search_pages(
        src, handler, query="x", country="us", location="United States", limit=120, calls=calls
    )
    assert [len(p) for p in pages] == [50, 50, 50]  # stops once 120 are in
    assert len(calls) == 3 and "/search/1?" in calls[0]
    calls.clear()
    pages = search_pages(
        Adzuna(keys=keys), handler, query="x", country="us", start_page=2, limit=500, calls=calls
    )
    assert len(pages) == 1 and "/search/3?" in calls[0] and "/search/4?" in calls[1]


def test_daily_budget_cap(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    tmp_path: Path,
) -> None:
    row = load_fixture("adzuna/search.json")["results"][0]
    full = {
        "results": [
            {**row, "id": str(i), "redirect_url": f"https://a.example/{i}"} for i in range(50)
        ]
    }
    calls: list[str] = []
    src = Adzuna(keys=keys)
    src.budget = DailyBudget("adzuna", 2, tmp_path)
    handler = lambda req: httpx.Response(200, json=full)  # noqa: E731
    pages = search_pages(src, handler, query="x", country="us", limit=1000, calls=calls)
    assert len(pages) == 2 and len(calls) == 2  # the budget, not MAX_PAGES, ended it
    # the count is on disk, so another run (a new instance) starts with nothing left
    again = Adzuna(keys=keys)
    again.budget = DailyBudget("adzuna", 2, tmp_path)
    assert search_pages(again, handler, query="x", country="us", calls=calls) == []
    assert len(calls) == 2
    assert adzuna.DAILY_BUDGET == 250 and adzuna.MAX_PAGES == 15
