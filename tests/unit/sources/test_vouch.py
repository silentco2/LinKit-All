from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.vouch import Vouch
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def serving(page: str) -> Callable[[httpx.Request], httpx.Response]:
    return lambda req: httpx.Response(200, text=page)


def test_reads_live_listings_from_the_flight(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Vouch(), serving(load_fixture("vouch/company.html")), board="cmghoj", calls=calls
    )
    assert "https://vouch.careers/companies/cmghoj" in calls
    assert len(pages) == 1 and len(pages[0]) == 2  # draft, unlisted, deactivated and id-less drop
    a, b = pages[0]
    assert a.title == "Senior Software Engineer" and a.company == "Laine"
    assert a.url == "https://vouch.careers/companies/cmghoj/cmjob1" and a.ats == "vouch"
    assert a.remote == "remote" and a.location == ""
    assert a.extra == {"board": "cmghoj", "id": "cmjob1"}
    assert a.posted_at is not None and a.posted_at.isoformat() == "2025-10-21T07:15:49.762000"
    # the pitch is escaped prose (its "<10" survives); the bracketed text does not unbalance the scan
    assert "Join a <10 person team building [the future]." in a.description
    assert "Ship production systems." in a.description and "NestJS." in a.description
    assert b.title == "[EMEA] Product Designer"
    assert b.remote == "hybrid"  # hybrid beats on-site when both are listed
    assert b.location == "Geneva, Switzerland"


def test_empty_board_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(Vouch(), serving(load_fixture("vouch/empty.html")), board="x") == [[]]
    assert search_pages(Vouch(), serving("<html/>"), board="x", start_page=1) == []


def test_markup_changes_fail_loudly(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    with pytest.raises(ValueError, match=r"no Next\.js payload"):
        search_pages(Vouch(), serving("<html><body>nothing</body></html>"), board="x")
    with pytest.raises(ValueError, match="no listings"):
        search_pages(Vouch(), serving(load_fixture("vouch/no_listings.html")), board="x")


def test_url_patterns() -> None:
    assert detect("https://vouch.careers/companies/cmghojtua00p5et0dvusuxx5o") == (
        "vouch",
        "cmghojtua00p5et0dvusuxx5o",
    )
    assert detect("vouch:abc") == ("vouch", "abc")
