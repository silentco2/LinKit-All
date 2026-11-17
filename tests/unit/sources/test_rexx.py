import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.rexx import Rexx, list_url
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def test_search_walks_by_the_cards_a_page_carried(search_pages, load_fixture):
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path != "/stellenangebote.html":
            return httpx.Response(404)
        html = (
            '<div id="joboffers"></div>'
            if "start" in req.url.params
            else load_fixture("rexx/list.html")
        )
        return httpx.Response(200, text=html)

    ((a, b),) = search_pages(Rexx(), handler, board="https://jobs.northwind.example", calls=calls)
    assert [c for c in calls if "robots" not in c] == [
        "https://jobs.northwind.example/stellenangebote.html",
        "https://jobs.northwind.example/stellenangebote.html?start=2",
    ]
    assert (a.title, a.company, a.location) == (
        "Softwareentwickler (m/w/d)",
        "Northwind",
        "Leipzig",
    )
    assert a.url == "https://jobs.northwind.example/Softwareentwickler-de-j101.html"
    assert a.extra == {"board": "https://jobs.northwind.example", "id": "101"}
    assert b.url == "https://jobs.northwind.example/Buchhalter-de-j102.html"
    assert (b.location, b.remote) == ("Dresden, Remote", "remote")  # older skin: the last column


def test_fetch_details_reads_the_posting_page(fetch_details, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture("rexx/detail.html"))

    stub = Rexx.cards(load_fixture("rexx/list.html"), "https://jobs.northwind.example/", "b")[0]
    full = fetch_details(Rexx(), handler, stub)
    assert full.description == "Code schreiben."
    assert full.posted_at is not None and full.posted_at.isoformat() == "2026-10-03T00:00:00"


def test_list_url_and_shorthand():
    assert list_url("jobs.acme.com") == "https://jobs.acme.com/stellenangebote.html"
    assert (
        list_url("https://jobs.acme.com/markt/")
        == "https://jobs.acme.com/markt/stellenangebote.html"
    )
    assert list_url("https://jobs.acme.com/jobs.html?x=1#y") == "https://jobs.acme.com/jobs.html"
    assert detect("rexx:https://jobs.acme.com") == ("rexx", "https://jobs.acme.com")
