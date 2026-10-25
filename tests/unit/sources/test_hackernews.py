import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.hackernews import HackerNews


def _handler(load_fixture, calls=None):
    routes = {
        "/api/v1/search_by_date": "hackernews/search.json",
        "/api/v1/items/49522897": "hackernews/thread_sept.json",
        "/api/v1/items/49156683": "hackernews/thread_aug.json",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(req.url.path)
        return httpx.Response(200, json=load_fixture(routes[req.url.path]))

    return handler


def test_it_reads_the_two_newest_hiring_threads(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(HackerNews(), _handler(load_fixture, calls))
    assert [len(p) for p in pages] == [2, 1]  # deleted, free-form and role-first posts dropped
    assert "/api/v1/items/48747976" not in calls  # July is outside the window
    modash, quill = pages[0]
    assert (modash.company, modash.title, modash.location) == (
        "Modash.io", "Senior Product Engineer", "Remote (Europe)",
    )  # fmt: skip
    assert modash.url == "https://news.ycombinator.com/item?id=49522903"
    assert modash.apply_url == "https://modash.io" and modash.remote == "remote"
    assert "Modash helps brands find creators." in modash.description
    assert modash.posted_at is not None and modash.posted_at.year == 2026
    assert (quill.company, quill.title, quill.location) == (
        "Quill", "Fullstack SWE", "Remote, PT/ET hours preferred",
    )  # fmt: skip
    acme = pages[1][0]
    assert (acme.company, acme.title, acme.location) == ("Acme & Co", "Backend Engineer", "")
    assert acme.apply_url == acme.url  # no link in the post: its own page


def test_start_page_skips_threads_already_done(search_pages, load_fixture):
    pages = search_pages(HackerNews(), _handler(load_fixture), start_page=1)
    assert [s.company for p in pages for s in p] == ["Acme & Co"]


def test_the_task_limit_stops_before_the_second_thread(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(HackerNews(), _handler(load_fixture, calls), limit=1)
    assert [len(p) for p in pages] == [1]
    assert "/api/v1/items/49156683" not in calls


def test_it_is_an_opt_in_aggregator():
    assert registry()["hackernews"].kind == "aggregator"
