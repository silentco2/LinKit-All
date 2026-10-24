import httpx

from linkit_all.sources.ats.betterteam import Betterteam, job_links
from linkit_all.sources.ats_detector import detect

BASE = "https://110grill.betterteam.com/"


def router(load_fixture, calls: list[str] | None = None):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if calls is not None:
            calls.append(req.url.path)
        if req.url.path == "/":
            return httpx.Response(200, text=load_fixture("betterteam/listing.html"))
        if req.url.path == "/bartender-21":
            return httpx.Response(200, text=load_fixture("betterteam/detail_bartender-21.html"))
        if req.url.path == "/line-cook-113":
            return httpx.Response(200, text=load_fixture("betterteam/detail_no_jobposting.html"))
        return httpx.Response(404)  # culinary-manager-39 is gone

    return handler


def test_job_links_resolve_dedupe_and_filter(load_fixture):
    assert job_links(load_fixture("betterteam/listing.html"), BASE) == [
        BASE + "bartender-21",
        BASE + "line-cook-113",
        BASE + "culinary-manager-39",
    ]
    html = '<a href="/a/b-12">x</a><a href="https://elsewhere.example/job-9">y</a><a href="/careers">z</a>'
    assert job_links(html, BASE) == []


def test_search_reads_each_posting_page(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(Betterteam(), router(load_fixture, calls), board="110grill")
    (stub,) = pages[0]  # one has no JobPosting, one is gone
    assert stub.title == "Bartender"
    assert stub.company == "110 Grill"
    assert stub.location == "North Conway, US"
    assert stub.url == BASE + "bartender-21"
    assert stub.extra == {"board": "110grill", "id": "bartender-21"}
    assert "Pour" in stub.description and "drinks" in stub.description
    assert "<" not in stub.description and "alert" not in stub.description
    assert stub.posted_at is not None and stub.posted_at.isoformat().startswith(
        "2026-06-09T15:07:41"
    )
    assert calls[0] == "/"


def test_resume_skips_the_pages_already_done(search_pages, load_fixture):
    assert search_pages(Betterteam(), router(load_fixture), board="110grill", start_page=1) == []


def test_url_patterns():
    assert detect("https://110grill.betterteam.com/bartender-21", [Betterteam()]) == (
        "betterteam",
        "110grill",
    )
