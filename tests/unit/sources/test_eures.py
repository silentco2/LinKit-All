import json

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.eures import Eures, country_code


def test_country_codes_accept_names_and_codes():
    assert country_code("Germany") == "de" and country_code(" DE ") == "de"
    assert country_code("Greece") == "el" and country_code("gr") == "el"
    assert country_code("Berlin") is None and country_code("") is None


def test_search_body_filters_by_keyword_country_and_period(search_pages, load_fixture):
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=load_fixture("eures/search.json"))

    search_pages(Eures(), handler, query="python", location="Germany", posted_within_days=7)
    (body,) = bodies
    assert body["keywords"] == [{"keyword": "python", "specificSearchCode": "EVERYWHERE"}]
    assert body["locationCodes"] == ["de"] and body["publicationPeriod"] == "LAST_WEEK"
    assert (body["page"], body["resultsPerPage"], body["sortSearch"]) == (1, 50, "MOST_RECENT")
    assert body["occupationUris"] == [] and body["requiredLanguages"] == []  # present, not null
    bodies.clear()
    search_pages(Eures(), handler, query="python", location="Berlin", posted_within_days=90)
    assert bodies[0]["locationCodes"] == [] and bodies[0]["publicationPeriod"] == "LAST_MONTH"


def test_search_maps_vacancies(search_pages, load_fixture):
    (page,) = search_pages(
        Eures(), lambda r: httpx.Response(200, json=load_fixture("eures/search.json")), query="x"
    )
    job, anon = page
    assert job.title == "Software Engineer"
    assert job.company == "SUSS MicroTec Solutions GmbH & Co. KG"
    assert job.location == "Germany; Greece"  # EURES calls Greece "EL"
    assert job.url == (
        "https://europa.eu/eures/portal/jv-se/jv-details/MTAwMDEtMTAwMTEzOTMxMS1TIDE?lang=en"
    )
    assert job.description == "We build things."
    assert job.posted_at is not None and job.posted_at.year == 2025
    assert anon.company == "Unknown" and anon.location == "France"


def test_paging_stops_at_the_reported_total(search_pages, load_fixture):
    pages_asked: list[int] = []
    row = load_fixture("eures/search.json")["jvs"][0]

    def handler(req: httpx.Request) -> httpx.Response:
        page = json.loads(req.content)["page"]
        pages_asked.append(page)
        jvs = [{**row, "id": f"{page}-{i}"} for i in range(50)]
        return httpx.Response(200, json={"numberRecords": 120, "jvs": jvs})

    pages = search_pages(Eures(), handler, query="x", limit=500)
    assert pages_asked == [1, 2, 3] and [len(p) for p in pages] == [50, 50, 50]
    pages_asked.clear()
    search_pages(Eures(), handler, query="x", limit=100, start_page=1)
    assert pages_asked == [2]  # limit 100 = two pages, the first already done


def test_tasks_and_registration():
    cfg = SearchConfig.model_validate({"search": {"queries": ["a"], "locations": ["Germany", ""]}})
    assert [(t.query, t.location) for t in Eures().tasks(cfg)] == [("a", "Germany"), ("a", "")]
    assert registry()["eures"].kind == "aggregator"
