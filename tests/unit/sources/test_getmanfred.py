import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.getmanfred import GetManfred
from linkit_all.sources.base import JobStub


def test_search_keeps_active_offers_and_maps_the_work_mode(search_pages, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("getmanfred/offers.json"))

    (page,) = search_pages(GetManfred(), handler)
    assert seen[0].url.params["lang"] == "ES"
    mango, acme = page  # the CLOSED offer is dropped
    assert (mango.title, mango.company, mango.location) == (
        "Sr. Product Designer", "Mango", "Barcelona, España",
    )  # fmt: skip
    assert mango.url == "https://www.getmanfred.com/ofertas-empleo/8407/mango-sr-designer"
    assert mango.remote == "hybrid" and acme.remote == "remote"
    assert mango.posted_at is not None and mango.posted_at.day == 11
    assert mango.description == ""  # the body comes from fetch_details
    assert mango.extra == {"id": 8407}


def test_the_task_limit_and_start_page_slice_the_list(search_pages, load_fixture):
    offer = load_fixture("getmanfred/offers.json")[0]
    offers = [{**offer, "id": i + 1} for i in range(250)]
    handler = lambda r: httpx.Response(200, json=offers)  # noqa: E731
    assert [len(p) for p in search_pages(GetManfred(), handler, limit=230)] == [100, 100, 30]
    assert [len(p) for p in search_pages(GetManfred(), handler, limit=230, start_page=2)] == [30]


def test_fetch_details_assembles_the_sections(fetch_details, load_fixture):
    stub = JobStub(
        source="getmanfred", title="t", company="c",
        url="https://www.getmanfred.com/ofertas-empleo/8407/mango-sr-designer",
    )  # fmt: skip
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=load_fixture("getmanfred/offer_8407.json"))

    out = fetch_details(GetManfred(), handler, stub)
    assert seen == ["/api/v2/public/offers/8407"]
    assert out.description == (
        "Intro text.\n\n- Design flows\n- Ship UI\n\nNice perks.\n\nTech stack: Figma, Sketch"
    )


def test_it_is_an_opt_in_aggregator():
    assert registry()["getmanfred"].kind == "aggregator"
