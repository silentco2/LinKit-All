from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.humanbit import HumanBit
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http

ONE = "job-0000-0000-0000-000000000001"
TWO = "job-0000-0000-0000-000000000002"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(routes: dict[str, str | int]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        for key in sorted(routes, key=len, reverse=True):
            if str(req.url).endswith(key):
                body = routes[key]
                return (
                    httpx.Response(body)
                    if isinstance(body, int)
                    else httpx.Response(200, text=body)
                )
        return httpx.Response(404)

    return handler


def test_listing_is_hydrated_from_detail_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    routes = {
        "/scrabble-jigsaw": load_fixture("humanbit/listing.html"),
        f"/jobs/{ONE}": load_fixture("humanbit/detail1.html"),
        f"/jobs/{TWO}": load_fixture("humanbit/detail2.html"),
    }
    pages = search_pages(HumanBit(), _serve(routes), board="scrabble-jigsaw")
    assert len(pages) == 1
    one, two = pages[0]
    assert one.title == "Senior Cost Accountant" and one.location == "Noida"
    assert one.company == "Scrabble & Jigsaw"  # org_name comes from the listing only
    assert one.url == f"https://jobs.humanbit.ai/scrabble-jigsaw/jobs/{ONE}"
    assert one.description == "Own the cost base in detail."  # the detail page's own row
    assert one.remote is None and one.extra["employment"] == ["full-time"]
    assert one.posted_at is not None and one.posted_at.year == 2026
    assert (
        one.extra["board"] == "scrabble-jigsaw" and one.extra["id"] == ONE and one.ats == "humanbit"
    )
    assert two.remote == "remote" and two.extra["employment"] == ["contract"]
    assert two.description == "Lead the sales org in detail."


def test_failed_detail_keeps_the_listing_copy_and_a_removed_posting_is_dropped(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    routes: dict[str, str | int] = {
        "/scrabble-jigsaw": load_fixture("humanbit/listing.html"),
        f"/jobs/{ONE}": 503,  # transport failure: keep what the listing knows
        f"/jobs/{TWO}": load_fixture("humanbit/notfound.html"),  # 200 without a job: gone
    }
    pages = search_pages(HumanBit(), _serve(routes), board="scrabble-jigsaw")
    assert [s.extra["id"] for s in pages[0]] == [ONE]
    assert pages[0][0].description == "Own the cost base."  # from the listing's own text row


def test_empty_board_and_markup_change(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    empty = _serve({"/acme": load_fixture("humanbit/empty.html")})
    assert search_pages(HumanBit(), empty, board="acme") == [[]]
    assert search_pages(HumanBit(), empty, board="acme", start_page=1) == []
    with pytest.raises(ValueError, match="no postings"):
        search_pages(
            HumanBit(), _serve({"/acme": load_fixture("humanbit/notfound.html")}), board="acme"
        )


def test_url_patterns() -> None:
    assert detect("https://jobs.humanbit.ai/scrabble-jigsaw") == ("humanbit", "scrabble-jigsaw")
    assert detect(f"https://jobs.humanbit.ai/scrabble-jigsaw/jobs/{ONE}") == (
        "humanbit",
        "scrabble-jigsaw",
    )
    assert detect("humanbit:acme") == ("humanbit", "acme")
