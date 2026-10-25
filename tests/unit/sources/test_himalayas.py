import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.himalayas import Himalayas


def _handler(load_fixture, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        offset = int(req.url.params["offset"])
        if calls is not None:
            calls.append(offset)
        name = {0: "himalayas/page1.json", 20: "himalayas/page2.json"}.get(offset)
        return httpx.Response(
            200, json=load_fixture(name) if name else {"totalCount": 45, "jobs": []}
        )

    return handler


def test_search_pages_by_offset_and_maps(search_pages, load_fixture):
    calls: list[int] = []
    pages = search_pages(
        Himalayas(), _handler(load_fixture, calls), limit=1000, posted_within_days=3650
    )
    assert calls == [0, 20, 40] and [len(p) for p in pages] == [
        2,
        1,
    ]  # the link-less row is dropped
    web, sales = pages[0]
    assert (web.title, web.company, web.location) == (
        "Web Engineer", "KraftPixel", "United States, Canada",
    )  # fmt: skip
    assert web.url == "https://himalayas.app/companies/kraftpixel/jobs/web-engineer"
    assert web.description == "Build web." and web.remote == "remote"  # trailer removed
    assert web.posted_at is not None and web.posted_at.year == 2026
    assert sales.company == "freshworks"  # the feed's "name" placeholder falls back to the slug


def test_a_feed_older_than_the_window_stops_after_one_page(search_pages, load_fixture):
    calls: list[int] = []
    search_pages(Himalayas(), _handler(load_fixture, calls), limit=1000, posted_within_days=1)
    assert calls == [0]


def test_the_task_limit_and_start_page(search_pages, load_fixture):
    calls: list[int] = []
    search_pages(Himalayas(), _handler(load_fixture, calls), limit=20, posted_within_days=3650)
    assert calls == [0]
    pages = search_pages(
        Himalayas(), _handler(load_fixture), limit=1000, posted_within_days=3650, start_page=1
    )
    assert [p[0].company for p in pages] == ["Peroptyx"]


def test_it_is_an_opt_in_aggregator():
    assert registry()["himalayas"].kind == "aggregator"
