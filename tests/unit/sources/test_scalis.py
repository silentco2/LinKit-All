import httpx
import pytest

from linkit_all.sources.ats.scalis import Scalis, description
from linkit_all.sources.ats_detector import detect

ID1 = "aaaa1111-0000-4000-8000-000000000001"


def _handler(load_fixture, calls=None):
    names = {"1": "page1", "2": "page2"}

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if calls is not None:
            calls.append(req.url.params["page"])
        page = names.get(req.url.params["page"], "empty")
        return httpx.Response(200, text=load_fixture(f"scalis/{page}.html"))

    return handler


def test_search_pages_to_an_empty_page(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(Scalis(), _handler(load_fixture, calls), board="boldbusiness")
    assert calls == ["1", "2", "3"]
    a, b = pages[0]
    (c,) = pages[1]
    assert (a.title, a.company, a.location) == (
        "Senior Backend Engineer",
        "Boldbusiness",
        "Bogota, CO",
    )
    assert a.url == f"https://boldbusiness.scalis.ai/job/{ID1}"
    assert a.remote == "remote" and a.description == "Build things."  # the HTML row wins
    assert a.extra["skills"] == ["Go", "Postgres"] and a.extra["employment"] == "FULL_TIME"
    assert a.salary_min is None and a.salary_interval is None
    assert a.posted_at is not None and a.posted_at.year == 2026
    # a back-reference company string in the flight does not break the posting
    assert (b.title, b.remote, b.description) == ("Support Engineer", "hybrid", "Ship features.")
    assert (b.salary_min, b.salary_max, b.salary_currency, b.salary_interval) == (
        20,
        30,
        "USD",
        "hour",
    )
    assert (c.title, c.remote, c.location) == ("Data Analyst", "onsite", "Manila, PH")


def test_resume_starts_at_the_checkpointed_page(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(
        Scalis(), _handler(load_fixture, calls), board="boldbusiness", start_page=1
    )
    assert calls == ["2", "3"] and [[s.title for s in p] for p in pages] == [["Data Analyst"]]


def test_description_prefers_html_and_falls_back_to_text():
    rows = {"28": "plain", "29": "<p>html</p>"}
    assert description({"description": "$28", "descriptionHtml": "$29"}, rows) == (
        "<p>html</p>",
        True,
    )
    assert description({"description": "$28", "descriptionHtml": "$99"}, rows) == ("plain", True)
    assert description({"description": "inline"}, rows) == ("inline", False)
    assert description({"description": "$99"}, rows) == ("", True)


def test_unresolved_descriptions_and_a_missing_listing(search_pages, load_fixture):
    broken = (
        load_fixture("scalis/page1.html").replace("28:T15", "xx:T15").replace("29:T14", "yy:T14")
    )
    broken = broken.replace("2a:Tf", "zz:Tf").replace("2b:T15", "ww:T15")

    def handler(req: httpx.Request) -> httpx.Response:
        text = broken if req.url.params.get("page") == "1" else load_fixture("scalis/empty.html")
        return httpx.Response(200, text=text)

    with pytest.raises(ValueError, match="none resolved"):
        search_pages(Scalis(), handler, board="boldbusiness")

    no_listing = load_fixture("scalis/empty.html").replace("initialData", "other")
    with pytest.raises(ValueError, match="no initialData"):
        search_pages(Scalis(), lambda req: httpx.Response(200, text=no_listing), board="acme")


def test_url_patterns():
    assert detect("https://boldbusiness.scalis.ai/jobs") == ("scalis", "boldbusiness")
    assert detect(f"https://boldbusiness.scalis.ai/job/{ID1}") == ("scalis", "boldbusiness")
    assert detect("scalis:boldbusiness") == ("scalis", "boldbusiness")
