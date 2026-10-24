import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.edjoin import Edjoin
from linkit_all.sources.base import JobStub


def test_search_maps_rows_dedupes_and_reads_pay(search_pages, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("edjoin/listing.json"))

    (page,) = search_pages(Edjoin(), handler)
    q = seen[0].url.params  # the three ids the endpoint dereferences must be present
    assert (q["catID"], q["districtID"], q["recruitmentCenterID"]) == ("0", "0", "0")
    assert (q["rows"], q["page"], q["days"], q["order"]) == ("200", "1", "14", "desc")
    tech, tutor, aide = page  # the repeated posting id is dropped
    assert (tech.title, tech.company) == ("Network Technician", "Alhambra Unified School District")
    assert tech.location == "Alhambra, California"
    assert tech.url == "https://www.edjoin.org/Home/JobPosting/2243913"
    assert tech.posted_at is not None and tech.posted_at.year == 2026
    assert (tech.salary_min, tech.salary_max) == (24.51, 32.13)
    assert (tech.salary_currency, tech.salary_interval) == ("USD", "hour")
    assert tutor.location == "Santa Clara, California"  # no city: the county stands in
    assert tutor.remote == "remote" and tutor.posted_at is None  # .NET MinValue
    assert (tutor.salary_min, tutor.salary_max, tutor.salary_interval) == (
        6097.87,
        6097.87,
        "month",
    )
    assert aide.salary_min is None and aide.salary_interval is None  # free-text pay boxes


def test_pages_are_walked_to_the_limit_and_resumed(search_pages, load_fixture):
    pages_asked: list[str] = []
    rows = load_fixture("edjoin/listing.json")["data"]

    def handler(req: httpx.Request) -> httpx.Response:
        page = int(req.url.params["page"])
        pages_asked.append(str(page))
        shifted = [{**r, "postingID": r["postingID"] + page * 100} for r in rows]
        data = shifted if page < 3 else []  # the third page is empty: the end of the index
        return httpx.Response(200, json={"totalRecords": 5000, "data": data})

    pages = search_pages(Edjoin(), handler, limit=1500)  # 500 rows per page, three pages
    assert pages_asked == ["1", "2", "3"] and len(pages) == 2
    pages_asked.clear()
    pages = search_pages(Edjoin(), handler, limit=1500, start_page=1)
    assert pages_asked == ["2", "3"] and len(pages) == 1
    pages_asked.clear()
    search_pages(Edjoin(), handler, limit=3)  # a small limit asks for that many rows, once
    assert pages_asked == ["1"]


def test_fetch_details_reads_the_ld_json_body(fetch_details, load_fixture):
    stub = JobStub(
        source="edjoin",
        title="t",
        company="c",
        url="https://www.edjoin.org/Home/JobPosting/2243913",
    )

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=load_fixture("edjoin/posting.html"))

    out = fetch_details(Edjoin(), handler, stub)
    assert out.description == "Job Summary\nMaintain the district network."
    assert fetch_details(Edjoin(), lambda r: httpx.Response(410), stub).description == ""


def test_it_is_an_opt_in_aggregator():
    assert registry()["edjoin"].kind == "aggregator"
