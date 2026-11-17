import httpx

from linkit_all.sources.ats.polymer import Polymer
from linkit_all.sources.ats_detector import detect


def test_search_stops_on_the_empty_page_not_the_metadata(search_pages, load_fixture):
    data = load_fixture("polymer/jobs.json")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params["page"] == "1":
            return httpx.Response(200, json=data)
        return httpx.Response(200, json={"items": [], "meta": {"is_last": False, "next_page": 3}})

    calls: list[str] = []
    ((a, b),) = search_pages(Polymer(), handler, board="northwind", calls=calls)
    assert calls == [
        "https://api.polymer.co/v1/hire/organizations/northwind/jobs?page=1",
        "https://api.polymer.co/v1/hire/organizations/northwind/jobs?page=2",
    ]
    assert (a.title, a.company) == ("Account Executive", "Northwind")
    assert a.location == "Denver, CO, United States" and a.remote == "hybrid"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-12T00:00:00"
    assert a.extra == {"board": "northwind", "id": "11", "salary_text": "$80k"}
    assert b.url == "https://jobs.polymer.co/northwind/12" and b.location == "Anywhere"
    assert b.posted_at is not None  # epoch seconds


def test_url_patterns():
    assert detect("https://jobs.polymer.co/northwind/11") == ("polymer", "northwind")
    assert detect("polymer:northwind") == ("polymer", "northwind")
