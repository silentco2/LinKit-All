import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.teamex import Teamex


def test_search_maps_active_postings_and_hides_anonymous_employers(search_pages, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("teamex/page1.json"))

    (page,) = search_pages(Teamex(), handler)
    assert dict(seen[0].url.params) == {"pageSize": "50", "pageIndex": "1"}
    job, hidden = page  # the inactive posting is dropped
    assert (job.title, job.company, job.location) == (
        "Senior Full-Stack Engineer", "Acme Health", "Argentina, Costa Rica",
    )  # fmt: skip
    assert job.url == "https://teamex.io/job/1506"
    assert "Overview" in job.description and "Build systems." in job.description
    assert "x()" not in job.description and "Skills: Docker, React" in job.description
    assert job.posted_at is not None and job.posted_at.month == 7
    assert hidden.company == "TeamEx"  # the payload names Secret Corp; it must not leak


def test_paging_stops_at_the_total_and_resumes_by_page(search_pages, load_fixture):
    asked: list[str] = []
    row = load_fixture("teamex/page1.json")["data"]["data"][0]

    def handler(req: httpx.Request) -> httpx.Response:
        page = int(req.url.params["pageIndex"])
        asked.append(str(page))
        rows = [{**row, "sequenceId": page * 100 + i} for i in range(50)]
        return httpx.Response(200, json={"data": {"paging": {"totalCount": 120}, "data": rows}})

    assert len(search_pages(Teamex(), handler, limit=1000)) == 3
    assert asked == ["1", "2", "3"]
    asked.clear()
    search_pages(Teamex(), handler, limit=1000, start_page=2)
    assert asked == ["3"]
    asked.clear()
    search_pages(Teamex(), handler, limit=10)
    assert asked == ["1"]


def test_an_empty_page_ends_the_walk(search_pages):
    assert search_pages(Teamex(), lambda req: httpx.Response(200, json={"data": {}})) == []


def test_it_is_an_opt_in_aggregator():
    assert registry()["teamex"].kind == "aggregator"
