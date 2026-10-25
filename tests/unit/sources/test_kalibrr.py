import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.kalibrr import Kalibrr


def _ok(data):
    return lambda req: httpx.Response(200, json=data)


def test_search_maps_postings_and_asks_for_the_country(search_pages, load_fixture):
    data = load_fixture("kalibrr/philippines.json")
    seen: list[dict[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=data)

    ((first, second, third, fourth),) = search_pages(
        Kalibrr(), handler, query="python", location="Manila, Philippines", limit=50
    )
    assert seen == [{"country": "Philippines", "text": "python", "limit": "50", "offset": "0"}]
    assert (first.title, first.company, first.location) == (
        "IT Director | Makati",
        "MedGrocer",
        "Makati, Metro Manila, Philippines",
    )
    assert first.url == "https://www.kalibrr.com/c/medgrocer/jobs/263258/it-director-makati"
    assert first.apply_url == first.url and first.extra == {"id": 263258}
    assert first.posted_at is not None and first.posted_at.year == 2026
    assert "IT Director" in first.description and "<" not in first.description
    assert (first.salary_min, first.salary_max) == (100000, 150000)
    assert (first.salary_currency, first.salary_interval) == ("PHP", "month")
    # a link through a redirector is opaque: the posting page stays the apply url
    assert second.apply_url == second.url and second.salary_min is None
    assert fourth.remote == "remote" and third.remote is None


def test_rows_from_another_country_are_dropped(search_pages, load_fixture):
    data = load_fixture("kalibrr/philippines.json")
    data["jobs"][0]["google_location"]["address_components"]["country"] = "Indonesia"
    pages = search_pages(Kalibrr(), _ok(data), query="x", location="Philippines")
    assert [s.extra["id"] for s in pages[0]] == [271382, 273103, 273204]


def test_a_direct_apply_link_shared_by_postings_is_an_intake_form(search_pages, load_fixture):
    data = load_fixture("kalibrr/philippines.json")
    urls = ["https://acme.example/apply", "https://other.example/x", "https://other.example/x"]
    for row, link in zip(data["jobs"], urls, strict=False):
        row["apply_redirect_url"] = link
    pages = search_pages(Kalibrr(), _ok(data), query="x", location="Philippines")
    first, second, third, _ = pages[0]
    assert first.apply_url == "https://acme.example/apply"
    assert second.apply_url == second.url and third.apply_url == third.url


def test_resume_and_unknown_country_fetch_nothing(search_pages):
    calls: list[str] = []
    kw = {"query": "x", "calls": calls}
    assert (
        search_pages(Kalibrr(), _ok({}), location="Manila, Philippines", start_page=1, **kw) == []
    )
    assert search_pages(Kalibrr(), _ok({}), location="Berlin, Germany", **kw) == []
    assert calls == []


def test_only_southeast_asian_locations_get_tasks():
    source = registry()["kalibrr"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {
            "search": {
                "queries": ["python"],
                "locations": ["Manila, Philippines", "Berlin, Germany", "Indonesia"],
            },
            "sources": {"enabled": ["kalibrr"]},
        }
    )
    assert source.is_enabled(cfg)
    assert [t.location for t in source.tasks(cfg)] == ["Manila, Philippines", "Indonesia"]
