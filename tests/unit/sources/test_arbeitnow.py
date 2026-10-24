import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.arbeitnow import Arbeitnow


def _handler(page1, calls):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.params["page"])
        if req.url.params["page"] == "1":
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json={"data": [], "links": {"next": None}})

    return handler


def test_search_maps_and_decodes_entity_encoded_bodies(search_pages, load_fixture):
    calls: list[str] = []
    # a wide window so the old fixture dates do not end the walk after page 1
    pages = search_pages(
        Arbeitnow(), _handler(load_fixture("arbeitnow/page1.json"), calls), posted_within_days=3650
    )
    assert calls == ["1", "2"] and len(pages) == 1  # the empty second page ends it
    data, cloud = pages[0]  # the posting without a slug is dropped
    assert (data.title, data.company, data.location) == ("Data Engineer", "Passerelle", "Berlin")
    assert data.url == "https://www.arbeitnow.com/jobs/companies/passerelle/data-engineer-berlin-1"
    assert data.description == "Build & ship." and data.remote == "remote"
    assert data.posted_at is not None and data.posted_at.year == 2026
    assert data.extra == {"id": "data-engineer-berlin-1"}
    assert "Kubernetes at scale" in cloud.description and "<" not in cloud.description
    assert cloud.remote == "remote"  # from "Remote possible" in the location text


def test_a_feed_that_is_all_older_than_the_window_stops(search_pages, load_fixture):
    calls: list[str] = []
    search_pages(Arbeitnow(), _handler(load_fixture("arbeitnow/page1.json"), calls))
    assert calls == ["1"]


def test_start_page_resumes_and_limit_caps_pages(search_pages, load_fixture):
    calls: list[str] = []
    handler = _handler(load_fixture("arbeitnow/page1.json"), calls)
    search_pages(Arbeitnow(), handler, start_page=1, posted_within_days=3650)
    assert calls == ["2"]
    calls.clear()
    search_pages(Arbeitnow(), handler, limit=100, posted_within_days=3650)
    assert calls == ["1"]  # 100 jobs = one page


def test_it_is_an_opt_in_aggregator_with_one_feed_task():
    source = registry()["arbeitnow"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["a", "b"]}, "sources": {"enabled": ["arbeitnow"]}}
    )
    assert source.is_enabled(cfg)
    (task,) = source.tasks(cfg)
    assert task.limit == 400  # one listing stands in for both queries
