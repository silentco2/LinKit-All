import httpx

from linkit_all.sources.ats.rippling import Rippling
from linkit_all.sources.ats_detector import detect

UUID = "3fa85f64-5717-4562-b3fc-2c963f66afa6"


def test_search_maps_the_list(search_pages, load_fixture):
    data = load_fixture("rippling/list.json")
    calls: list[str] = []
    pages = search_pages(
        Rippling(), lambda req: httpx.Response(200, json=data), board="acme", calls=calls
    )
    a, b = pages[0]
    assert (a.title, a.company, a.location) == (
        "Backend Engineer",
        "Acme",
        "London, United Kingdom",
    )
    assert a.url == f"https://ats.rippling.com/acme/jobs/{UUID}"
    assert a.extra == {"board": "acme", "id": UUID} and a.remote is None and a.ats == "rippling"
    assert b.remote == "remote"
    assert calls == ["https://ats.rippling.com/api/v1/board/acme/jobs"]


def test_fetch_details_takes_the_role_body_only(search_pages, fetch_details, load_fixture):
    data = load_fixture("rippling/list.json")
    stub = search_pages(Rippling(), lambda req: httpx.Response(200, json=data), board="acme")[0][0]
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, json=load_fixture("rippling/detail.json"))

    full = fetch_details(Rippling(), handler, stub)
    assert "Build the backend." in full.description and "boilerplate" not in full.description
    assert full.posted_at is not None and full.posted_at.isoformat() == "2026-03-11T16:37:20.990000"
    assert calls[-1] == f"https://ats.rippling.com/api/v1/board/acme/jobs/{UUID}"


def test_a_gone_posting_keeps_the_stub(search_pages, fetch_details, load_fixture):
    data = load_fixture("rippling/list.json")
    stub = search_pages(Rippling(), lambda req: httpx.Response(200, json=data), board="acme")[0][0]
    assert fetch_details(Rippling(), lambda req: httpx.Response(404), stub) == stub


def test_url_patterns():
    assert detect(f"https://ats.rippling.com/acme/jobs/{UUID}") == ("rippling", "acme")
    assert detect("https://ats.rippling.com/en-GB/acme/jobs") == ("rippling", "acme")
    assert detect("rippling:acme") == ("rippling", "acme")
