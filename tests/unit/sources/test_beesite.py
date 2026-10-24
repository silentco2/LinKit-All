import json

import httpx
import pytest

from linkit_all.sources.ats.beesite import BeeSite, body_from_page
from linkit_all.sources.ats_detector import detect

PORSCHE = "porsche-beesite-production-gjb.app.beesite.de"
PAGE = "https://jobs.porsche.com/index.php?ac=jobad&id="


def test_search_without_a_body_in_the_record(search_pages, load_fixture):
    data = load_fixture("beesite/porsche_search.json")
    calls: list[str] = []
    pages = search_pages(
        BeeSite(), lambda req: httpx.Response(200, json=data), board=PORSCHE, calls=calls
    )
    stubs = pages[0]
    assert len(stubs) == 3
    first = stubs[0]
    assert first.url == PAGE + "17854"
    assert first.title.startswith("Consultant Leitungsrecht")
    assert first.company == "MHP - A Porsche Company"
    assert first.description == ""  # read from the posting page later
    assert first.extra == {"board": PORSCHE, "id": "17854"}
    assert first.posted_at is not None and first.posted_at.isoformat() == "2025-09-09T00:00:00"
    assert first.apply_url and "application" in first.apply_url
    assert f"https://{PORSCHE}/search?data=" in calls[0]
    sent = json.loads(httpx.URL(calls[0]).params["data"])
    assert sent["SearchParameters"] == {"FirstItem": 1, "CountItem": 100}


def test_a_record_that_carries_its_body(search_pages, load_fixture):
    data = load_fixture("beesite/mercedes_search.json")
    (stub,) = search_pages(
        BeeSite(),
        lambda req: httpx.Response(200, json=data),
        board="mercedes-benz-beesite-production-gjb.app.beesite.de",
    )[0]
    assert stub.url.startswith("https://jobs.mercedes-benz.com/")
    assert "Mercedes-Benz" in stub.description
    assert stub.location == "Stuttgart, Germany"
    assert stub.company == "Mercedes-Benz Group AG"


def test_paging_by_the_stated_total(search_pages, load_fixture):
    item = load_fixture("beesite/porsche_search.json")["SearchResult"]["SearchResultItems"][0]

    def page(n: int, count: int) -> list[dict]:
        return [{**item, "MatchedObjectId": f"{n}-{i}"} for i in range(count)]

    def handler(req: httpx.Request) -> httpx.Response:
        first = json.loads(req.url.params["data"])["SearchParameters"]["FirstItem"]
        items = page(first, 100) if first == 1 else page(first, 5)
        return httpx.Response(
            200, json={"SearchResult": {"SearchResultCountAll": 105, "SearchResultItems": items}}
        )

    pages = search_pages(BeeSite(), handler, board=PORSCHE)
    assert [len(p) for p in pages] == [100, 5]


def test_only_beesite_hosts(search_pages):
    with pytest.raises(ValueError):
        search_pages(BeeSite(), lambda req: httpx.Response(500), board="jobs.porsche.com")


def test_page_description_variants(load_fixture):
    # a JobPosting block opening with the template's stray "entryLevel" token
    assert body_from_page(load_fixture("beesite/porsche_posting_ldjson.html")).startswith(
        "Aufgaben"
    )
    assert "&lt;" not in body_from_page(load_fixture("beesite/porsche_posting_ldjson.html"))
    # a posting handled outside the portal has no JobPosting: the template container
    assert "Interface person between Customer and Chassis software department" in body_from_page(
        load_fixture("beesite/porsche_posting_no_ldjson.html")
    )
    assert body_from_page("<html><body><p>Not available any more.</p></body></html>") == ""


def test_fetch_details_reads_the_employer_page_once(search_pages, fetch_details, load_fixture):
    data = load_fixture("beesite/porsche_search.json")
    stub = search_pages(BeeSite(), lambda req: httpx.Response(200, json=data), board=PORSCHE)[0][0]
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        seen.append(str(req.url))
        return httpx.Response(200, text=load_fixture("beesite/porsche_posting_ldjson.html"))

    out = fetch_details(BeeSite(), handler, stub)
    assert out.description.startswith("Aufgaben")
    assert seen == [PAGE + "17854"]
    # a stub that already has its body costs no request
    assert fetch_details(BeeSite(), handler, out) == out
    assert len(seen) == 1


def test_url_patterns():
    assert detect(f"https://{PORSCHE}/search?data=x", [BeeSite()]) == ("beesite", PORSCHE)
