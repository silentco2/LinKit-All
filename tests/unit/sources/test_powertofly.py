import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.powertofly import PowerToFly


def _pages(load_fixture, calls):
    pages = {"1": load_fixture("powertofly/page1.json"), "2": load_fixture("powertofly/page2.json")}

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.params["page"])
        return httpx.Response(200, json=pages[req.url.params["page"]])

    return handler


def test_search_follows_next_page_until_it_is_null(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(PowerToFly(), _pages(load_fixture, calls), limit=1000)
    assert calls == ["1", "2"] and [len(p) for p in pages] == [3, 2]
    abbvie = pages[0][0]
    assert (abbvie.title, abbvie.company) == (
        "Analista di laboratorio - Tempo determinato 12 mesi",
        "AbbVie",
    )
    assert abbvie.url == "https://powertofly.com/jobs/detail/1502923"
    assert abbvie.extra == {"id": 1502923} and abbvie.apply_url == abbvie.url
    # city, state, country titles: "location" is the work arrangement, not geography
    assert abbvie.location == "Gallicano Nel Lazio, Lazio, Italy"
    assert abbvie.remote == "onsite" and "<" not in abbvie.description
    assert pages[1][0].company == "NASCAR" and pages[1][0].location.endswith("United States")


def test_limit_caps_pages_and_start_page_resumes(search_pages, load_fixture):
    calls: list[str] = []
    search_pages(PowerToFly(), _pages(load_fixture, calls), limit=50)
    assert calls == ["1"]  # 50 jobs = one page
    calls.clear()
    search_pages(PowerToFly(), _pages(load_fixture, calls), limit=1000, start_page=1)
    assert calls == ["2"]


def test_arrangement_region_fallback_and_unusable_rows(search_pages, load_fixture):
    page = load_fixture("powertofly/page2.json")
    first, second = page["data"]
    first["location"], first["city"], first["state"], first["country"] = "Remote", None, None, None
    first["location_regions"] = ["USA", "Canada"]
    second["company"] = {}
    ((stub,),) = search_pages(PowerToFly(), lambda r: httpx.Response(200, json=page), limit=50)
    assert (stub.remote, stub.location) == ("remote", "USA, Canada")


def test_an_empty_page_ends_the_walk(search_pages):
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.params["page"])
        return httpx.Response(200, json={"data": [], "meta": {"next_page": 2}})

    assert search_pages(PowerToFly(), handler, limit=1000) == [] and calls == ["1"]


def test_it_is_an_opt_in_aggregator_with_one_feed_task():
    source = registry()["powertofly"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["a", "b"]}, "sources": {"enabled": ["powertofly"]}}
    )
    assert source.is_enabled(cfg) and len(source.tasks(cfg)) == 1
