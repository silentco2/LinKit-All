import json

import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.tyomarkkinatori import Tyomarkkinatori
from linkit_all.sources.base import JobStub


def _search(load_fixture, asked):
    def handler(req: httpx.Request) -> httpx.Response:
        region = json.loads(req.content)["filters"]["regions"][0]
        asked.append(region)
        try:
            return httpx.Response(200, json=load_fixture(f"tyomarkkinatori/search_{region}.json"))
        except FileNotFoundError:
            return httpx.Response(200, json={"content": [], "lastPage": 0})

    return handler


def _stub() -> JobStub:
    url = "https://tyomarkkinatori.fi/henkiloasiakkaat/avoimet-tyopaikat/a1/fi"
    return JobStub(source="tyomarkkinatori", url=url, title="Old", company="Old Oy")


def test_search_walks_regions_dedupes_and_maps(search_pages, load_fixture):
    asked: list[str] = []
    pages = search_pages(Tyomarkkinatori(), _search(load_fixture, asked))
    assert asked[:2] == ["01", "02"] and len(asked) == 19
    assert [len(p) for p in pages] == [2]  # a1 repeats in region 06 and is dropped there
    dev, cook = pages[0]
    assert (dev.title, dev.company, dev.location) == (
        "Ohjelmistokehittäjä", "Bambu Food Oy", "Helsinki, Finland",
    )  # fmt: skip
    assert dev.url == "https://tyomarkkinatori.fi/henkiloasiakkaat/avoimet-tyopaikat/a1/fi"
    assert dev.posted_at is not None and dev.posted_at.day == 15
    assert (cook.company, cook.location) == ("Ravintola Oy", "Stockholm")  # foreign: no Finland
    assert cook.url.endswith("/a2/en")


def test_the_limit_stops_the_walk(search_pages, load_fixture):
    asked: list[str] = []
    pages = search_pages(Tyomarkkinatori(), _search(load_fixture, asked), limit=2)
    assert [len(p) for p in pages] == [2] and asked == ["01"]


def test_resume_skips_pages_already_stored(search_pages, load_fixture):
    assert search_pages(Tyomarkkinatori(), _search(load_fixture, []), start_page=1) == []


def test_details_fill_the_body_and_the_authoritative_fields(fetch_details, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("tyomarkkinatori/detail_a1.json"))

    stub = fetch_details(Tyomarkkinatori(), handler, _stub())
    assert seen[0].url.path.endswith("/public/jobpostings/a1")
    assert (stub.title, stub.company) == ("Software Developer", "Hyperion Robotics")
    assert stub.description == "Build things.\nLocation: Helsinki"
    assert stub.posted_at is not None and stub.posted_at.day == 10


def test_a_rate_limited_detail_keeps_the_stub(fetch_details):
    stub = fetch_details(Tyomarkkinatori(), lambda req: httpx.Response(403), _stub())
    assert stub == _stub()


def test_it_is_an_opt_in_aggregator():
    assert registry()["tyomarkkinatori"].kind == "aggregator"
