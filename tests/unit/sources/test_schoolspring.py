import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.schoolspring import SchoolSpring
from linkit_all.sources.base import JobStub


def _search(load_fixture, calls):
    data = load_fixture("schoolspring/search.json")

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(dict(req.url.params))
        return httpx.Response(200, json=data if req.url.params["page"] == "1" else _empty())

    return handler


def _empty():
    return {"success": True, "value": {"jobsList": []}}


def test_search_maps_listing_rows_and_pages_until_empty(search_pages, load_fixture):
    calls: list[dict[str, str]] = []
    pages = search_pages(
        SchoolSpring(), _search(load_fixture, calls), query="network administrator", limit=500
    )
    assert [c["page"] for c in calls] == ["1", "2"]
    assert calls[0]["keyword"] == "network administrator" and calls[0]["size"] == "100"
    ((first, second, third),) = pages
    assert (first.title, first.company, first.location) == (
        "Network Administrator",
        "Richmond County School District",
        "Rockingham, North Carolina",
    )
    assert first.url == "https://www.schoolspring.com/jobdetail?jobId=5967360"
    assert first.extra == {"id": 5967360} and first.apply_url == first.url
    assert first.posted_at is not None and first.posted_at.isoformat() == "2026-10-21T04:00:00"
    assert second.title == "Network Administrator ($82,693.18+)"  # entities decoded
    assert third.company == "Salado Ind School District"


def test_limit_caps_the_listing_and_resume_continues(search_pages, load_fixture):
    calls: list[dict[str, str]] = []
    ((a, b),) = search_pages(SchoolSpring(), _search(load_fixture, calls), query="x", limit=2)
    assert (a.extra["id"], b.extra["id"]) == (5967360, 5955739) and len(calls) == 1
    calls.clear()
    search_pages(SchoolSpring(), _search(load_fixture, calls), query="x", start_page=1)
    assert calls[0]["page"] == "2"


def test_a_page_repeating_known_rows_ends_the_walk_and_a_refusal_raises(search_pages, load_fixture):
    data = load_fixture("schoolspring/search.json")
    calls: list[str] = []
    pages = search_pages(
        SchoolSpring(), lambda r: httpx.Response(200, json=data), query="x", limit=500, calls=calls
    )
    assert len(pages) == 1 and len(calls) == 2  # page 2 adds nothing new
    refused = {"success": False, "message": "boom", "value": None}
    with pytest.raises(RuntimeError, match="boom"):
        search_pages(SchoolSpring(), lambda r: httpx.Response(200, json=refused), query="x")


def test_fetch_details_fills_body_and_places(fetch_details, load_fixture):
    detail = load_fixture("schoolspring/detail.json")
    stub = JobStub(
        source="schoolspring",
        url="https://www.schoolspring.com/jobdetail?jobId=5967360",
        title="Network Administrator",
        company="Richmond County School District",
        location="Rockingham, North Carolina",
    )
    seen: list[httpx.URL] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url)
        return httpx.Response(200, json=detail)

    out = fetch_details(SchoolSpring(), handler, stub)
    assert (
        seen[0].path == "/api/Jobs/5967360"
        and seen[0].params["domainName"] == "www.schoolspring.com"
    )
    assert "Network Administrator" in out.description and "<" not in out.description
    assert out.location == "Rockingham, North Carolina" and out.company == stub.company


def test_fetch_details_leaves_the_stub_alone_when_the_posting_is_gone(fetch_details):
    stub = JobStub(
        source="schoolspring",
        url="https://www.schoolspring.com/jobdetail?jobId=1",
        title="t",
        company="c",
    )
    gone = {"success": False, "message": "JobDetail not found : 1", "value": {"jobInfo": None}}
    assert fetch_details(SchoolSpring(), lambda r: httpx.Response(200, json=gone), stub) == stub


def test_it_is_an_opt_in_aggregator_with_one_task_per_query():
    source = registry()["schoolspring"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {
            "search": {"queries": ["a", "b"], "locations": ["Texas"]},
            "sources": {"enabled": ["schoolspring"]},
        }
    )
    assert source.is_enabled(cfg) and len(source.tasks(cfg)) == 2
