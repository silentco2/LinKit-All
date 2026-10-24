import httpx

from linkit_all.sources.ats.pinpoint import Pinpoint
from linkit_all.sources.ats_detector import detect


def test_search_joins_the_body_sections(search_pages, load_fixture):
    data = load_fixture("pinpoint/postings.json")
    calls: list[str] = []
    pages = search_pages(
        Pinpoint(), lambda req: httpx.Response(200, json=data), board="acme", calls=calls
    )
    a, b = pages[0]
    assert (a.title, a.company, a.location) == ("Pipeline Engineer", "Acme", "Annapolis, Maryland")
    assert a.url == "https://acme.pinpointhq.com/en/postings/abc"
    for part in ("Build pipelines.", "Own ingest", "Go", "Health cover."):
        assert part in a.description
    assert a.remote == "onsite" and a.ats == "pinpoint" and a.extra["id"] == "217178"
    assert b.location == "Remote"  # no city/province: falls back to the display name
    assert b.remote == "remote"
    assert calls == ["https://acme.pinpointhq.com/postings.json"]


def test_a_later_page_and_an_empty_board(search_pages):
    def empty(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": []})

    assert search_pages(Pinpoint(), empty, board="acme") == [[]]
    assert search_pages(Pinpoint(), empty, board="acme", start_page=1) == []


def test_url_patterns():
    assert detect("https://acme.pinpointhq.com/en/postings/abc") == ("pinpoint", "acme")
    assert detect("pinpoint:acme") == ("pinpoint", "acme")
    assert detect("https://www.pinpointhq.com/pricing") is None
