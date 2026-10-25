import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.jobdanmark import JobDanmark
from linkit_all.sources.base import JobStub


def _list_handler(load_fixture, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(req.url.path)
        page = req.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=load_fixture(f"jobdanmark/page{page}.json"))

    return handler


def test_search_pages_to_total_pages_and_maps(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(
        JobDanmark(), _list_handler(load_fixture, calls), limit=300, posted_within_days=3650
    )
    assert calls == ["/api/jobsearch/search/1", "/api/jobsearch/search/2"]
    assert [len(p) for p in pages] == [1, 1]  # the title-less row is dropped
    dev, tester = pages[0][0], pages[1][0]
    assert (dev.title, dev.company) == ("Backend Developer", "Acme A/S")
    assert dev.location == "Storegade 25, 6261 Bredebro, Danmark"
    assert dev.url == "https://jobdanmark.dk/job/acme-dev" and dev.description == ""
    assert (dev.posted_at.year, dev.posted_at.month, dev.posted_at.day) == (2026, 7, 5)
    assert tester.url == "https://jobdanmark.dk/job/beta-test"  # query string dropped
    assert tester.location == "Danmark"


def test_start_page_and_task_limit(search_pages, load_fixture):
    pages = search_pages(
        JobDanmark(), _list_handler(load_fixture), limit=300, posted_within_days=3650, start_page=1
    )
    assert [p[0].company for p in pages] == ["Beta ApS"]
    calls: list[str] = []
    search_pages(
        JobDanmark(), _list_handler(load_fixture, calls), limit=30, posted_within_days=3650
    )
    assert calls == ["/api/jobsearch/search/1"]


def test_fetch_details_reads_the_job_posting(fetch_details, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture("jobdanmark/detail.html"))

    stub = JobStub(
        source="jobdanmark", url="https://jobdanmark.dk/job/acme-dev", title="t", company="c"
    )
    done = fetch_details(JobDanmark(), handler, stub)
    assert done.description == "Full body here"
    assert done.posted_at is not None and done.posted_at.day == 7


def test_fetch_details_without_a_job_posting_keeps_the_stub(fetch_details):
    handler = lambda req: httpx.Response(200, text="<html></html>")  # noqa: E731
    stub = JobStub(source="jobdanmark", url="https://jobdanmark.dk/job/x", title="t", company="c")
    assert fetch_details(JobDanmark(), handler, stub).description == ""


def test_it_is_an_opt_in_aggregator():
    assert registry()["jobdanmark"].kind == "aggregator"
