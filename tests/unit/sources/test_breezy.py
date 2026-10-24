import httpx

from linkit_all.sources.ats.breezy import Breezy
from linkit_all.sources.ats_detector import detect


def test_search_maps_the_json_list(search_pages, load_fixture):
    data = load_fixture("breezy/list.json")
    calls: list[str] = []
    pages = search_pages(
        Breezy(), lambda req: httpx.Response(200, json=data), board="acme", calls=calls
    )
    a, b = pages[0]
    assert (a.title, a.company, a.location) == ("Senior Designer", "Acme Inc", "Yerevan, Armenia")
    assert a.url == "https://acme.breezy.hr/p/52-senior-designer"
    assert a.remote is None
    assert a.posted_at is not None and a.posted_at.year == 2025
    assert a.extra["employment"] == "Full-Time" and a.ats == "breezy"
    assert b.remote == "remote" and b.company == "Acme"
    assert calls == ["https://acme.breezy.hr/json"]


def test_fetch_details_reads_the_position_page(search_pages, fetch_details, load_fixture):
    data = load_fixture("breezy/list.json")
    stub = search_pages(Breezy(), lambda req: httpx.Response(200, json=data), board="acme")[0][0]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture("breezy/detail.html"))

    out = fetch_details(Breezy(), handler, stub)
    assert "Do the design." in out.description and "<" not in out.description


def test_fetch_details_keeps_the_stub_when_the_page_has_no_body(
    search_pages, fetch_details, load_fixture
):
    data = load_fixture("breezy/list.json")
    stub = search_pages(Breezy(), lambda req: httpx.Response(200, json=data), board="acme")[0][0]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<html><body>nothing</body></html>")

    assert fetch_details(Breezy(), handler, stub) == stub


def test_robots_disallow_is_respected(search_pages, fetch_details, load_fixture):
    data = load_fixture("breezy/list.json")
    stub = search_pages(Breezy(), lambda req: httpx.Response(200, json=data), board="acme")[0][0]

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/robots.txt", "page must not be fetched"
        return httpx.Response(200, text="User-agent: *\nDisallow: /p/\n")

    assert fetch_details(Breezy(), handler, stub) == stub


def test_url_patterns():
    assert detect("https://agbo.breezy.hr/p/1-x", [Breezy()]) == ("breezy", "agbo")
