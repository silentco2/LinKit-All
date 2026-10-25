import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.jobicy import Jobicy


def test_search_maps_the_feed(search_pages, load_fixture):
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.params["count"])
        return httpx.Response(200, json=load_fixture("jobicy/feed.json"))

    pages = search_pages(Jobicy(), handler)
    assert seen == ["50"] and [len(p) for p in pages] == [1]  # the id-less row is dropped
    job = pages[0][0]
    assert (job.title, job.company, job.location) == (
        "Service Technician", "Municipal Emergency Services", "USA",
    )  # fmt: skip
    assert job.url == "https://jobicy.com/jobs/147014-service-tech" and job.remote == "remote"
    assert job.description == "Fix gear." and job.posted_at is not None


def test_start_page_beyond_the_single_page_yields_nothing(search_pages, load_fixture):
    handler = lambda req: httpx.Response(200, json=load_fixture("jobicy/feed.json"))  # noqa: E731
    assert search_pages(Jobicy(), handler, start_page=1) == []


def test_it_is_an_opt_in_aggregator():
    assert registry()["jobicy"].kind == "aggregator"
