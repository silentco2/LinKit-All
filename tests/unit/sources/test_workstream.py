from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.workstream import Workstream, cards_of, page_url, posting_id
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http

COOK = "/j/965a796b/moxies/pickering-79247/line-cook-09eacfc8"


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))  # fast Http


def handler_for(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/j/965a796b/positions":
            page = "listing_p2" if req.url.params.get("page") == "2" else "listing_p1"
            return httpx.Response(200, text=load_fixture(f"workstream/{page}.html"))
        if path == COOK:
            return httpx.Response(200, text=load_fixture("workstream/posting.html"))
        if path.endswith("server-b8dc419f"):
            return httpx.Response(200, text=load_fixture("workstream/posting_no_body.html"))
        return httpx.Response(404)  # robots.txt, and the dishwasher posting that has gone

    return handler


def test_walks_the_pages_and_reads_each_posting(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Workstream(), handler_for(load_fixture), board="965a796b", calls=calls)
    listed = [c for c in calls if c.endswith("/positions") or "page=2" in c]
    assert listed == [
        "https://www.workstream.us/j/965a796b/positions",
        "https://www.workstream.us/j/965a796b/positions?page=2",
    ]
    assert (
        len(pages) == 1 and len(pages[0]) == 1
    )  # server has no body, dishwasher 404s, cook repeats
    job = pages[0][0]
    assert job.title == "Line Cook" and job.company == "FineCasual"
    assert job.url == f"https://www.workstream.us{COOK}"  # no ?locale=en
    assert job.location == "1355 Kingston Rd, Pickering, ON L1V 1B8, Canada"
    assert job.description.startswith("You will cook.") and "alert" not in job.description
    assert job.description.endswith("Pay: $17.00 - 20.00 per hour")
    assert job.salary_min is None and job.salary_currency is None  # the "$" is unqualified
    assert job.ats == "workstream" and job.posted_at is None
    assert job.extra == {"board": "965a796b", "id": "09eacfc8", "employment": "Full-time"}


def test_single_brand_employer_follows_the_listing_the_page_states(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    brand = "https://www.workstream.us/j/965a796b/moxies/positions"
    root = f"<html><body><script>var searchBaseUrl = \"x\"; var searchBaseUrl = '{brand}';</script></body></html>"

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/j/965a796b/positions":
            return httpx.Response(200, text=root)  # the brand root: no cards, states the listing
        if req.url.path == "/j/965a796b/moxies/positions":
            page = load_fixture("workstream/listing_p1.html").replace(
                "totalPages = 2", "totalPages = 1"
            )
            return httpx.Response(200, text=page)
        return handler_for(load_fixture)(req)

    calls: list[str] = []
    pages = search_pages(Workstream(), handler, board="965a796b", calls=calls)
    assert brand in calls and [len(p) for p in pages] == [1]


def test_resume_and_failures(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert (
        search_pages(Workstream(), handler_for(load_fixture), board="965a796b", start_page=1) == []
    )
    with pytest.raises(ValueError, match="no positions listing"):
        search_pages(
            Workstream(),
            lambda req: httpx.Response(200, text="<html>nope</html>"),
            board="965a796b",
        )
    with pytest.raises(httpx.HTTPStatusError):  # a retired employer answers 410
        search_pages(Workstream(), lambda req: httpx.Response(410), board="965a796b")


def test_parsing_helpers_and_url_patterns(load_fixture: Callable[[str], Any]) -> None:
    ids = {
        COOK: "09eacfc8",
        f"https://www.workstream.us{COOK}?locale=en": "09eacfc8",
        f"{COOK}/apply": "",
        "/j/965a796b/moxies/pickering-79247": "",
        "/j/965a796b/positions": "",
        "/j/965a796b/moxies/pickering-79247/line-cook-09EACFC8": "",  # ids are lower-case hex
    }
    assert {href: posting_id(href) for href in ids} == ids
    cards = cards_of(load_fixture("workstream/listing_p1.html"))
    assert [(c.id, c.employment) for c in cards] == [("09eacfc8", "Full-time"), ("b8dc419f", None)]
    assert page_url("https://x.test/p?a=1&page=7", 3) == "https://x.test/p?a=1&page=3"
    assert detect(f"https://www.workstream.us{COOK}") == ("workstream", "965a796b")
    assert detect("https://www.workstream.us/j/finecasual") == ("workstream", "finecasual")
