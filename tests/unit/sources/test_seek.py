import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.seek import Seek
from linkit_all.sources.base import JobStub


def _search(data, calls):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url)
        return httpx.Response(200, json=data if req.url.params["page"] == "1" else {"data": []})

    return handler


def test_search_maps_postings_for_the_australian_market(search_pages, load_fixture):
    calls: list[httpx.URL] = []
    ((payroll, tax, subway),) = search_pages(
        Seek(), _search(load_fixture("seek/search.json"), calls), query="payroll",
        location="Sydney", limit=200, posted_within_days=3650,
    )  # fmt: skip
    first = calls[0]
    assert (first.host, first.path) == ("www.seek.com.au", "/api/jobsearch/v5/search")
    assert dict(first.params) == {
        "siteKey": "AU-Main", "where": "Sydney", "keywords": "payroll",
        "page": "1", "pageSize": "100", "sortmode": "ListedDate",
    }  # fmt: skip
    assert (payroll.title, payroll.company, payroll.location) == (
        "Payroll Officer",
        "Mars Recruitment",
        "Epping, Melbourne VIC",
    )
    assert (
        payroll.url == "https://www.seek.com.au/job/95478718" and payroll.extra["id"] == "95478718"
    )
    assert payroll.posted_at is not None and payroll.posted_at.isoformat() == "2026-10-25T03:22:45"
    assert payroll.description == "" and payroll.remote == "onsite"  # the body comes from details
    assert tax.remote == "hybrid" and subway.company == "Subway Shamim Group"


def test_the_new_zealand_market_and_default_scope(search_pages, load_fixture):
    calls: list[httpx.URL] = []
    search_pages(Seek(), _search(load_fixture("seek/search.json"), calls), query="x",
                 location="New Zealand", posted_within_days=3650)  # fmt: skip
    assert calls[0].host == "www.seek.co.nz"
    assert calls[0].params["siteKey"] == "NZ-Main" and calls[0].params["where"] == "All New Zealand"
    calls.clear()
    search_pages(Seek(), _search(load_fixture("seek/search.json"), calls), query="x",
                 location="Australia", posted_within_days=3650)  # fmt: skip
    assert calls[0].params["where"] == "All Australia"


def test_private_advertisers_are_dropped_and_remote_wins_over_onsite(search_pages, load_fixture):
    data = load_fixture("seek/search.json")
    data["data"][0]["companyName"] = "Private Advertiser"
    data["data"][0]["advertiser"] = {"description": "Private Advertiser"}
    data["data"][1]["workArrangements"] = {
        "data": [{"label": {"text": "On-site"}}, {"label": {"text": "Remote"}}]
    }
    ((tax, _),) = search_pages(Seek(), _search(data, []), query="x", location="Sydney",
                               posted_within_days=3650)  # fmt: skip
    assert tax.remote == "remote"


def test_paging_stops_on_an_empty_page_the_limit_or_a_dated_out_page(search_pages, load_fixture):
    data = load_fixture("seek/search.json")
    calls: list[httpx.URL] = []
    pages = search_pages(Seek(), _search(data, calls), query="x", location="Sydney",
                         limit=1000, posted_within_days=3650)  # fmt: skip
    assert len(pages) == 1 and len(calls) == 2  # the empty second page ends it
    calls.clear()
    search_pages(Seek(), _search(data, calls), query="x", location="Sydney", limit=100,
                 posted_within_days=3650)  # fmt: skip
    assert len(calls) == 1  # 100 jobs = one page
    calls.clear()
    search_pages(Seek(), _search(data, calls), query="x", location="Sydney", limit=1000,
                 posted_within_days=0)  # fmt: skip
    assert len(calls) == 1  # newest first: all older than the window
    calls.clear()
    search_pages(Seek(), _search(data, calls), query="x", location="Sydney", limit=1000,
                 start_page=1, posted_within_days=3650)  # fmt: skip
    assert calls[0].params["page"] == "2"


def _stub(url="https://www.seek.com.au/job/95478107"):
    return JobStub(source="seek", url=url, title="Chef", company="Assaggini")


def test_fetch_details_posts_the_graphql_query(fetch_details, load_fixture):
    detail = load_fixture("seek/detail.json")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=detail)

    out = fetch_details(Seek(), handler, _stub())
    assert str(seen[0].url) == "https://www.seek.com.au/graphql"
    assert b'"jobId":"95478107"' in seen[0].content.replace(b" ", b"")
    assert "Assaggini Wine Bar" in out.description and "<" not in out.description


def test_a_rate_limit_stops_details_for_the_rest_of_the_run(mock_transport, load_fixture):
    import asyncio

    from linkit_all.sources.http import Http

    limited = {"errors": [{"extensions": {"code": "RATE_LIMITED"}}], "data": None}
    detail = load_fixture("seek/detail.json")
    answers = iter([limited, detail])
    calls: list[str] = []
    source = Seek()

    async def go() -> list[JobStub]:
        transport = mock_transport(lambda r: httpx.Response(200, json=next(answers)), calls)
        async with httpx.AsyncClient(transport=transport) as client:
            http = Http(client, attempts=1)
            return [
                await source.fetch_details(http, _stub()),
                await source.fetch_details(http, _stub()),
            ]

    first, second = asyncio.run(go())
    assert first.description == "" and second.description == ""
    assert len(calls) == 1  # the second stub made no request


def test_http_429_also_stops_details_and_a_server_error_does_not(fetch_details):
    source = Seek()
    assert fetch_details(source, lambda r: httpx.Response(500), _stub()).description == ""
    assert source._details_stopped is False
    assert fetch_details(source, lambda r: httpx.Response(429), _stub()).description == ""
    assert source._details_stopped is True


def test_a_foreign_url_is_left_alone(fetch_details):
    stub = _stub("https://example.com/job/1")
    assert fetch_details(Seek(), lambda r: httpx.Response(500), stub) == stub


def test_it_is_an_opt_in_aggregator_and_skips_other_countries():
    source = registry()["seek"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {
            "search": {
                "queries": ["a"],
                "locations": ["Sydney", "Auckland, New Zealand", "Berlin, Germany"],
            },
            "sources": {"enabled": ["seek"]},
        }
    )
    assert [t.location for t in source.tasks(cfg)] == ["Sydney", "Auckland, New Zealand"]
