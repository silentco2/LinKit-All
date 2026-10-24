import base64

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.arbeitsagentur import Arbeitsagentur
from linkit_all.sources.base import JobStub


def test_tasks_are_query_by_location():
    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["python"], "locations": ["Berlin", ""]}}
    )
    tasks = Arbeitsagentur().tasks(cfg)
    assert [(t.query, t.location) for t in tasks] == [("python", "Berlin"), ("python", "")]
    assert Arbeitsagentur().tasks(SearchConfig()) == []  # nothing to search for


def test_search_sends_the_public_key_and_maps_postings(search_pages, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("arbeitsagentur/search.json"))

    (page,) = search_pages(
        Arbeitsagentur(), handler, query="python", location="Hagen", posted_within_days=500
    )
    (req,) = seen
    assert req.headers["X-API-Key"] == "jobboerse-jobsuche"
    q = req.url.params
    assert (q["was"], q["wo"], q["page"], q["size"], q["veroeffentlichtseit"]) == (
        "python", "Hagen", "1", "100", "100",  # the API takes at most 100 days
    )  # fmt: skip
    own, relisted = page
    assert (own.title, own.company) == ("Python Entwickler (m/w/d)", "EUROPART Holding GmbH")
    assert own.location == "Hagen, Westfalen, Nordrhein Westfalen, Deutschland"
    assert own.url == "https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1003871444-S"
    assert own.apply_url == own.url and own.remote == "hybrid"
    assert own.posted_at is not None and own.posted_at.day == 16
    assert relisted.apply_url == "https://aubi-plus.example/x" and relisted.location == "Berlin"
    assert relisted.remote is None


def test_search_pages_until_a_short_page(search_pages, load_fixture):
    rows = load_fixture("arbeitsagentur/search.json")["ergebnisliste"] * 50  # 100 rows
    pages_asked: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        pages_asked.append(req.url.params["page"])
        full = req.url.params["page"] == "1"
        body = {"ergebnisliste": rows if full else rows[:3], "maxErgebnisse": 103}
        return httpx.Response(200, json=body)

    pages = search_pages(Arbeitsagentur(), handler, query="x")
    assert pages_asked == ["1", "2"] and [len(p) for p in pages] == [100, 3]
    pages_asked.clear()
    search_pages(Arbeitsagentur(), handler, query="x", start_page=1)
    assert pages_asked == ["2"]


def test_fetch_details_reads_the_description_by_base64_reference(fetch_details, load_fixture):
    ref = "10001-1003871444-S"
    stub = JobStub(
        source="arbeitsagentur", title="t", company="c",
        url=f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{ref}",
    )  # fmt: skip
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("arbeitsagentur/detail.json"))

    out = fetch_details(Arbeitsagentur(), handler, stub)
    assert seen[0].url.path.endswith("/jobdetails/" + base64.b64encode(ref.encode()).decode())
    assert seen[0].headers["X-API-Key"] == "jobboerse-jobsuche"
    assert out.description == "Wir suchen einen Python Entwickler.\nAufgaben:\n- Backend"
    gone = fetch_details(Arbeitsagentur(), lambda r: httpx.Response(404), stub)
    assert gone.description == ""


def test_it_is_registered_as_an_aggregator():
    source = registry()["arbeitsagentur"]
    assert source.kind == "aggregator" and not source.url_patterns
