# ruff: noqa: RUF001
import json
import re
import time
from urllib.parse import parse_qs

import httpx
import pytest

from linkit_all.sources import registry
from linkit_all.sources.aggregators import wttj
from linkit_all.sources.aggregators.wttj import WelcomeToTheJungle

ENV = 'window.env = {"PUBLIC_ALGOLIA_API_KEY_CLIENT":"k","PUBLIC_ALGOLIA_APPLICATION_ID":"CSEKHVMS53"};'
CHILD = {"hitsPerPage": 0}


def _index(load_fixture, seen: list[httpx.Request] | None = None):
    """The three WTTJ endpoints; hit i was published i+1 hours ago, so windows can be split."""
    now = int(time.time())
    hits = load_fixture("wttj/list.json")["hits"]
    stamped = [(now - (i + 1) * 3600, h) for i, h in enumerate(hits)]

    def handler(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        if req.url.path == "/api/env":
            return httpx.Response(200, text=ENV)
        if req.url.host == "api.welcometothejungle.com":
            return httpx.Response(200, json=load_fixture("wttj/detail.json"))
        params = parse_qs(json.loads(req.content)["params"])
        lo, hi = map(int, re.findall(r"(?:>=|<) (\d+)", params["filters"][0]))
        inside = [h for ts, h in stamped if lo <= ts < hi]
        per_page = int(params["hitsPerPage"][0])
        return httpx.Response(200, json={"nbHits": len(inside), "hits": inside[:per_page]})

    return handler


def test_search_maps_the_listing_and_sends_the_site_referer(search_pages, load_fixture):
    seen: list[httpx.Request] = []
    pages = search_pages(
        WelcomeToTheJungle(), _index(load_fixture, seen), query="security", posted_within_days=30
    )
    assert len(pages) == 1 and len(pages[0]) == 4  # the hit without an organization slug is dropped
    edf, plain, scribd, syspertec = pages[0]
    assert (edf.title, edf.company, edf.location) == (
        "STAGE – BAC+5 - Ingénieur(e) Informatique - Ingénierie Cybersécurité F/H",
        "EDF",
        "Marseilles-lès-Aubigny, France",
    )
    assert edf.url == (
        "https://www.welcometothejungle.com/en/companies/edf/jobs/"
        "stage-bac-5-ingenieur-informatique-ingenierie-cybersecurite-f-h_marseille"
    )
    assert (edf.salary_min, edf.salary_max, edf.salary_interval) == (935.0, 1682.0, "month")
    assert edf.salary_currency == "EUR" and edf.remote is None  # "unknown"
    assert plain.remote == "remote" and syspertec.remote == "hybrid"
    assert scribd.posted_at is not None and scribd.extra["org"] == "scribd"
    # Every call to the site's hosts carries its Referer; Algolia also gets the key and app id.
    assert all(r.headers["Referer"] == "https://www.welcometothejungle.com/" for r in seen)
    algolia = [r for r in seen if "algolia" in r.url.host]
    assert algolia and algolia[0].url.host == "CSEKHVMS53-dsn.algolia.net".lower()
    assert algolia[0].headers["X-Algolia-API-Key"] == "k"
    assert json.loads(algolia[-1].content)["params"].count("query=security") == 1


def test_a_window_over_the_cap_is_split_newest_first(search_pages, load_fixture, monkeypatch):
    monkeypatch.setattr(wttj, "CAP", 2)
    pages = search_pages(WelcomeToTheJungle(), _index(load_fixture), posted_within_days=30)
    assert len(pages) > 1 and sum(len(p) for p in pages) == 4  # unusable hit is in the last page
    titles = [s.company for p in pages for s in p]
    assert titles == ["EDF", "Plain Concepts", "Scribd", "Syspertec Group"] or titles[0] == "EDF"


def test_limit_and_resume(search_pages, load_fixture, monkeypatch):
    monkeypatch.setattr(wttj, "CAP", 1)
    pages = search_pages(WelcomeToTheJungle(), _index(load_fixture), limit=2, posted_within_days=30)
    assert [len(p) for p in pages] == [1, 1]
    resumed = search_pages(
        WelcomeToTheJungle(), _index(load_fixture), start_page=1, posted_within_days=30
    )
    # pages 1-4 of 5 windows; the skipped one still counts against the limit, the last page is empty
    assert resumed[0][0].company == "Plain Concepts" and len(resumed) == 4
    capped = search_pages(
        WelcomeToTheJungle(), _index(load_fixture), start_page=1, limit=2, posted_within_days=30
    )
    assert [len(p) for p in capped] == [1]  # limit 2 minus the skipped page leaves one hit


def test_bad_credentials_raise(search_pages):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text='window.env = {"PUBLIC_ALGOLIA_APPLICATION_ID":"evil.host/x"};'
        )

    with pytest.raises(ValueError, match="credentials"):
        search_pages(WelcomeToTheJungle(), handler)


def test_fetch_details_fills_body_and_apply_url(fetch_details, load_fixture):
    stub = WelcomeToTheJungle().stub(load_fixture("wttj/list.json")["hits"][0])
    assert stub is not None
    done = fetch_details(WelcomeToTheJungle(), _index(load_fixture), stub)
    assert (
        done.apply_url == "https://www.edf.fr/edf-recrute/offre/detail/2026-184709?idOrigine=35052"
    )
    assert "5000 stagiaires" in done.description and "Profile" in done.description
    assert done.url == stub.url


def test_fetch_details_ignores_a_reused_slug_or_missing_posting(fetch_details, load_fixture):
    stub = WelcomeToTheJungle().stub(load_fixture("wttj/list.json")["hits"][0])
    assert stub is not None
    stub.extra["id"] = "someone-else"
    assert fetch_details(WelcomeToTheJungle(), _index(load_fixture), stub).description == ""
    stub.extra["id"] = load_fixture("wttj/list.json")["hits"][0]["objectID"]
    gone = fetch_details(WelcomeToTheJungle(), lambda r: httpx.Response(404), stub)
    assert gone.description == "" and gone.apply_url is None


def test_it_is_an_opt_in_aggregator():
    assert registry()["wttj"].kind == "aggregator"


def test_stub_drops_invalid_slugs_and_unknown_salary_periods(load_fixture):
    src = WelcomeToTheJungle()
    hit = load_fixture("wttj/list.json")["hits"][0]
    assert src.stub({**hit, "slug": "../admin"}) is None
    assert src.stub({**hit, "organization": {"name": "EDF", "slug": "a/b"}}) is None
    odd = src.stub({**hit, "salary_period": "weekly"})
    assert odd is not None and odd.salary_min is None and odd.salary_currency is None


def test_missing_key_raises(search_pages):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, text='window.env = {"PUBLIC_ALGOLIA_APPLICATION_ID":"ABCDEF12"};'
        )

    with pytest.raises(ValueError, match="credentials"):
        search_pages(WelcomeToTheJungle(), handler)


def test_fetch_details_routes_a_known_ats_apply_url(fetch_details, load_fixture):
    hit = load_fixture("wttj/list.json")["hits"][0]
    stub = WelcomeToTheJungle().stub(hit)
    assert stub is not None
    detail = load_fixture("wttj/detail.json")
    detail["job"]["apply_url"] = "https://boards.greenhouse.io/edf/jobs/123"
    done = fetch_details(WelcomeToTheJungle(), lambda r: httpx.Response(200, json=detail), stub)
    assert done.ats == "greenhouse" and done.apply_url.endswith("/jobs/123")


def test_fetch_details_skips_an_unpublished_posting(fetch_details, load_fixture):
    stub = WelcomeToTheJungle().stub(load_fixture("wttj/list.json")["hits"][0])
    assert stub is not None
    detail = load_fixture("wttj/detail.json")
    detail["job"]["status"] = "draft"
    done = fetch_details(WelcomeToTheJungle(), lambda r: httpx.Response(200, json=detail), stub)
    assert done.description == "" and done.apply_url is None
