import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.remotli import Remotli


def _ok(data):
    return lambda req: httpx.Response(200, json=data)


def test_search_unwraps_rows_and_maps_postings(search_pages, load_fixture):
    data = load_fixture("remotli/page1.json")
    ((tether, cdq, archlet),) = search_pages(Remotli(), _ok(data), limit=20)
    assert (tether.title, tether.company, tether.location) == (
        "Head of Regulatory Affairs-Europe ( Digital Assets & Fintech exposure)",
        "Tether",
        "Luxemburg",
    )
    assert tether.url.startswith("https://careers.tether.io/") and tether.apply_url == tether.url
    assert tether.extra == {"id": "7778"} and tether.remote is None  # an onsite Swiss/EU place
    assert tether.posted_at is not None and tether.posted_at.isoformat() == "2026-10-24T12:39:49"
    assert "<" not in tether.description
    assert cdq.company == "CDQ AG" and archlet.location == "Zurich"


def test_inactive_and_unusable_rows_are_dropped_and_remote_locations_flagged(
    search_pages, load_fixture
):
    data = load_fixture("remotli/page1.json")
    data["jobs"][0]["jobs"]["status"] = "closed"
    data["jobs"][1]["jobs"]["location"] = "Remote-EMEA"
    data["jobs"][2]["jobs"]["id"] = 0
    ((stub,),) = search_pages(Remotli(), _ok(data), limit=20)
    assert (stub.company, stub.remote) == ("CDQ AG", "remote")


def test_paging_follows_total_pages_and_limit(search_pages, load_fixture):
    data = load_fixture("remotli/page1.json")  # totalPages = 15
    calls: list[str] = []
    pages = search_pages(Remotli(), _ok(data), limit=40, calls=calls, posted_within_days=3650)
    assert len(pages) == 2 and [c.split("page=")[1] for c in calls] == ["1", "2"]
    calls.clear()
    search_pages(Remotli(), _ok(data), limit=40, start_page=1, calls=calls, posted_within_days=3650)
    assert [c.split("page=")[1] for c in calls] == ["2"]


def test_a_failing_later_page_keeps_the_walk_but_a_first_page_failure_raises(
    search_pages, load_fixture
):
    data = load_fixture("remotli/page1.json")

    def later_fails(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(200, json=data) if req.url.params["page"] == "1" else httpx.Response(403)
        )

    pages = search_pages(Remotli(), later_fails, limit=100, posted_within_days=3650)
    assert [len(p) for p in pages] == [3]
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(Remotli(), lambda r: httpx.Response(403), limit=100)


def test_it_is_an_opt_in_aggregator_with_one_feed_task():
    source = registry()["remotli"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["a", "b"]}, "sources": {"enabled": ["remotli"]}}
    )
    assert source.is_enabled(cfg) and len(source.tasks(cfg)) == 1
