from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.northstone import Northstone, canonical, parse_board
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
        if path == "/positions/":
            return httpx.Response(200, text=load_fixture("northstone/listing.html"))
        if path == "/positions/senior-engineer/":
            return httpx.Response(200, text=load_fixture("northstone/detail_remote.html"))
        if path == "/positions/ops-lead/":
            return httpx.Response(200, text=load_fixture("northstone/detail_onsite.html"))
        if path == "/positions/not-a-posting/":
            return httpx.Response(200, text="<html><body>FAQ</body></html>")
        return httpx.Response(404)

    return handler


def test_listing_then_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Northstone(), make_handler(load_fixture), board="vetted.enzrossi.com/positions", calls=calls
    )
    assert "https://vetted.enzrossi.com/positions/" in calls  # the trailing slash is kept
    assert len(pages) == 1
    # The page with no JobPosting is dropped, as are the bare listing, other sections, deeper paths.
    assert [j.title for j in pages[0]] == ["Senior Engineer", "Ops Lead"]
    a, b = pages[0]
    assert a.url == "https://vetted.enzrossi.com/positions/senior-engineer/"
    assert a.company == "EnzRossi" and a.remote == "remote" and a.ats == "northstone"
    assert a.location == "Brazil, Argentina"  # no jobLocation: the accepted countries
    assert a.description == "Role\nShip features."
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-07-14T13:34:41.575000"
    assert a.extra == {
        "board": "vetted.enzrossi.com/positions",
        "id": "6f1c0d2e-aaaa-bbbb-cccc-000000000001",
        "employment": "FULL_TIME",
        "valid_through": None,
    }
    assert b.url == "https://vetted.enzrossi.com/positions/ops-lead/"
    assert b.company == "Enzrossi"  # a posting without hiringOrganization: named after the host
    assert b.location == "Calgary, Alberta, CA" and b.remote is None
    assert b.extra["id"] == "zr-4521"
    assert b.posted_at is not None and b.posted_at.date().isoformat() == "2026-07-01"


def test_resume_skips_earlier_chunks(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(
        Northstone(),
        make_handler(load_fixture),
        board="vetted.enzrossi.com/positions",
        start_page=1,
    )
    assert pages == []


def test_board_shape() -> None:
    assert parse_board(" www.revun.com/careers/ ") == ("www.revun.com", "careers")
    for bad in ("www.revun.com", "www.revun.com/a/b", "/careers"):
        with pytest.raises(ValueError, match="must be <host>/<section>"):
            parse_board(bad)
    assert canonical("https://x.com/careers/a") == "https://x.com/careers/a/"
    assert canonical("https://x.com/careers/a/") == "https://x.com/careers/a/"
    assert canonical("https://x.com/careers/a?b=1") == "https://x.com/careers/a/?b=1"


def test_url_patterns() -> None:
    assert detect("https://www.revun.com/careers") == ("northstone", "www.revun.com/careers")
    assert detect("https://vetted.enzrossi.com/positions/senior-engineer") == (
        "northstone",
        "vetted.enzrossi.com/positions",
    )
    assert detect("northstone:www.revun.com/careers") == ("northstone", "www.revun.com/careers")
    assert detect("https://www.revun.com/about") is None
