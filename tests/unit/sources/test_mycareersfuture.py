import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.mycareersfuture import PAGE, MyCareersFuture


def _ok(data):
    return lambda req: httpx.Response(200, json=data)


def _full_page(row: dict, start: int) -> dict:
    return {"results": [{**row, "uuid": f"u{start + i}"} for i in range(PAGE)]}


def test_search_maps_postings(search_pages, load_fixture):
    data = load_fixture("mycareersfuture/page.json")
    seen: list[dict[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=data)

    ((first, second, third),) = search_pages(MyCareersFuture(), handler, query="python", limit=100)
    assert seen == [{"limit": "100", "page": "0", "search": "python", "sortBy": "new_posting_date"}]
    assert (first.title, first.company, first.location) == (
        "Process Control Engineer (Manufacturing/PCS/Python, East Region)",
        "HKM HR MANAGEMENT PTE. LTD.",
        "Singapore",
    )
    assert first.url == "https://www.mycareersfuture.gov.sg/job/0269f9c83cb4f431fd9e380f440f66d4"
    assert first.extra == {"id": "0269f9c83cb4f431fd9e380f440f66d4"}
    assert first.posted_at is not None and first.posted_at.isoformat() == "2026-10-25T00:00:00"
    assert "Python" in first.description and "<" not in first.description
    assert (first.salary_min, first.salary_max) == (4000, 5000)
    assert (first.salary_currency, first.salary_interval) == ("SGD", "month")
    assert second.company == "THE RESOLUTE HUNTER PTE. LTD." and third.title == "Data Engineer"


def test_overseas_address_hiring_company_and_unusable_rows(search_pages, load_fixture):
    data = load_fixture("mycareersfuture/page.json")
    data["results"][0]["address"] = {"isOverseas": True, "overseasCountry": "Malaysia"}
    data["results"][1]["hiringCompany"] = {"name": "Real Client Pte Ltd"}
    data["results"][2]["uuid"] = ""
    ((first, second),) = search_pages(MyCareersFuture(), _ok(data), query="x")
    assert first.location == "Malaysia" and second.company == "Real Client Pte Ltd"


def test_pages_until_a_short_page_or_the_limit(search_pages, load_fixture):
    row = load_fixture("mycareersfuture/page.json")["results"][0]
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        page = int(req.url.params["page"])
        return httpx.Response(
            200, json=_full_page(row, page * PAGE) if page < 2 else {"results": [row]}
        )

    pages = search_pages(MyCareersFuture(), handler, query="x", limit=1000, calls=calls)
    assert [len(p) for p in pages] == [PAGE, PAGE, 1] and len(calls) == 3
    calls.clear()
    assert len(search_pages(MyCareersFuture(), handler, query="x", limit=PAGE, calls=calls)) == 1
    calls.clear()
    search_pages(MyCareersFuture(), handler, query="x", limit=1000, start_page=2, calls=calls)
    assert len(calls) == 1 and "page=2" in calls[0]


def test_a_dated_out_page_stops_the_walk(search_pages, load_fixture):
    row = load_fixture("mycareersfuture/page.json")["results"][0]
    calls: list[str] = []
    page = _full_page({**row, "metadata": {"newPostingDate": "2020-01-01"}}, 0)
    search_pages(MyCareersFuture(), _ok(page), query="x", limit=1000, calls=calls)
    assert len(calls) == 1  # newest first: everything on page 1 is older than the window


def test_a_failing_later_page_keeps_what_was_gathered_but_a_first_page_failure_raises(
    search_pages, load_fixture
):
    row = load_fixture("mycareersfuture/page.json")["results"][0]

    def later_fails(req: httpx.Request) -> httpx.Response:
        if req.url.params["page"] == "0":
            return httpx.Response(200, json=_full_page(row, 0))
        return httpx.Response(403)

    pages = search_pages(MyCareersFuture(), later_fails, query="x", limit=1000)
    assert [len(p) for p in pages] == [PAGE]
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(MyCareersFuture(), lambda r: httpx.Response(403), query="x")


def test_it_is_an_opt_in_aggregator_with_query_tasks():
    source = registry()["mycareersfuture"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {
            "search": {"queries": ["a", "b"], "locations": ["Singapore", "Remote"]},
            "sources": {"enabled": ["mycareersfuture"]},
        }
    )
    assert len(source.tasks(cfg)) == 2  # the portal has no place filter: one task per query
