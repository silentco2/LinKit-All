from collections.abc import Callable
from typing import Any

import httpx
from boards_util import router, run_details, run_search

from linkit_all.sources.boards.remotedotcom import RemoteDotCom, description, listing


def _routes(load_fixture: Callable[[str], Any]) -> dict[str, Any]:
    return {
        "all?page=1": load_fixture("remotedotcom/page1.txt"),
        "all?page=2": load_fixture("remotedotcom/page2.txt"),
        "/senior-backend-developer-j1a": load_fixture("remotedotcom/posting.txt"),
    }


def test_listing_pages_are_read_through_the_flight(load_fixture: Callable[[str], Any]) -> None:
    calls: list[httpx.Request] = []
    pages = run_search(RemoteDotCom(), router(_routes(load_fixture), calls))
    assert all(r.headers["RSC"] == "1" for r in calls if "/robots.txt" not in str(r.url))
    assert [len(p) for p in pages] == [2, 1]  # the draft is dropped; stops at totalPages
    assert not any("page=3" in str(r.url) for r in calls)
    remote, hybrid = pages[0]
    assert remote.url == "https://remote.com/jobs/proxify-c114/senior-backend-developer-j1a"
    assert (remote.title, remote.company) == ("Senior Backend Developer", "Proxify")
    assert remote.remote == "remote" and remote.location == "South Africa, North America"
    assert remote.extra["id"] == "senior-backend-developer-j1a" and remote.ats == "remotedotcom"
    assert remote.posted_at is not None and remote.posted_at.day == 14
    # 300000-600000 minor units of EUR a month is 3000-6000
    assert (remote.salary_min, remote.salary_max) == (3000, 6000)
    assert (remote.salary_currency, remote.salary_interval) == ("EUR", "month")
    # braces and brackets in a title do not unbalance the object scan
    assert hybrid.title == "Tax Analyst {Remote} [LATAM]"
    assert hybrid.remote == "hybrid" and hybrid.location == "Iasi, Romania"
    assert hybrid.salary_min is None
    assert pages[1][0].location == "Worldwide" and pages[1][0].salary_interval == "year"


def test_resume_and_limit(load_fixture: Callable[[str], Any]) -> None:
    routes = _routes(load_fixture)
    resumed = run_search(RemoteDotCom(), router(routes), start_page=1)
    assert [s.title for p in resumed for s in p] == ["Support Engineer"]
    limited = run_search(RemoteDotCom(), router(routes), limit=1)
    assert [len(p) for p in limited] == [1]


def test_listing_without_jobs_data_is_empty() -> None:
    assert listing("no data here") == {}
    assert run_search(RemoteDotCom(), router({"all?page=1": "2:[]"})) == [[]]


def test_details_come_from_the_posting_flight(load_fixture: Callable[[str], Any]) -> None:
    (page, *_) = run_search(RemoteDotCom(), router(_routes(load_fixture)), limit=1)
    full = run_details(RemoteDotCom(), router(_routes(load_fixture)), page[0])
    assert "Build services." in full.description and "café" in full.description
    assert "<" not in full.description
    assert description("0:[]") == ""
