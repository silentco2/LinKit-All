from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.friendwork import FriendWork
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_salary_and_fields(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    data = load_fixture("friendwork/itgeo.json")
    seen: list[httpx.URL] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url)
        return httpx.Response(200, json=data)

    pages = search_pages(FriendWork(), handler, board="c656f1c111eb44075d21d77f57216c72")
    assert seen[0].params["token"] == "c656f1c111eb44075d21d77f57216c72"  # noqa: S105
    assert len(pages) == 1 and len(pages[0]) == 2
    a, b = pages[0]
    assert a.title == "Middle backend developer (.NET)" and a.company == "ITGEO"
    assert a.url == "https://jobs.friend.work/c656f1c111eb44075d21d77f57216c72/6080"
    assert a.location == "Москва" and a.remote == "onsite"
    assert (a.salary_min, a.salary_max) == (150000, 170000)
    assert a.salary_currency == "RUB" and a.salary_interval == "month"
    assert a.posted_at is not None and a.posted_at.year == 2019
    assert a.extra["id"] == "6080" and a.ats == "friendwork"
    assert b.salary_min is None and b.salary_max == 200000  # upper bound only


def test_remote_and_no_salary(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    data = load_fixture("friendwork/wowvendor.json")
    pages = search_pages(FriendWork(), lambda r: httpx.Response(200, json=data), board="wowvendor")
    first = pages[0][0]
    assert first.company == "WowVendor" and first.remote == "remote"
    assert first.url == "https://jobs.friend.work/WowVendor/125340"
    assert any(s.salary_currency is None for s in pages[0])
    assert (
        search_pages(
            FriendWork(), lambda r: httpx.Response(200, json=data), board="w", start_page=1
        )
        == []
    )


def test_url_patterns() -> None:
    assert detect("https://jobs.friend.work/tedo/12345") == ("friendwork", "tedo")
    assert detect("friendwork:skillbox") == ("friendwork", "skillbox")
