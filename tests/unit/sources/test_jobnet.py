import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.jobnet import Jobnet


def test_search_maps_ads_and_sends_the_csrf_header(search_pages, load_fixture):
    headers: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        headers.append(req.headers["x-csrf"])
        return httpx.Response(200, json=load_fixture("jobnet/page1.json"))

    pages = search_pages(Jobnet(), handler, limit=300, posted_within_days=3650)
    assert headers == ["1"] and [len(p) for p in pages] == [2]  # all 3 ads seen: no second request
    own, external = pages[0]
    assert (own.title, own.company, own.location) == (
        "IT-supportelev",
        "ipnordic A/S",
        "Gråsten, Danmark",
    )
    assert (
        own.url == "https://job.jobnet.dk/CV/FindWork/Details/c1dc33fa-9c57-4592-a050-36ecda5bdfc1"
    )
    assert own.apply_url == own.url and own.description == "Er du nysgerrig"
    assert own.posted_at is not None
    assert external.apply_url == "https://acme.example/jobs/1"


def test_it_pages_until_an_empty_page(search_pages, load_fixture):
    pages_asked: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        page = req.url.params["PageNumber"]
        pages_asked.append(page)
        body = load_fixture("jobnet/page1.json") if page == "1" else {"jobAds": []}
        return httpx.Response(200, json=body | {"totalJobAdCount": 9999} if page == "1" else body)

    pages = search_pages(Jobnet(), handler, limit=300, posted_within_days=3650)
    assert pages_asked == ["1", "2"] and len(pages) == 1


def test_the_task_limit_caps_the_pages(search_pages, load_fixture):
    asked: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append(req.url.params["PageNumber"])
        return httpx.Response(
            200, json=load_fixture("jobnet/page1.json") | {"totalJobAdCount": 9999}
        )

    search_pages(Jobnet(), handler, limit=100, posted_within_days=3650)
    assert asked == ["1"]


def test_it_is_an_opt_in_aggregator():
    assert registry()["jobnet"].kind == "aggregator"
