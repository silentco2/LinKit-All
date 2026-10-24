import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.getonbrd import GetOnBrd


def _handler(load_fixture, calls):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        route = {
            "/api/v0/categories": "getonbrd/categories.json",
            "/api/v0/categories/programming/jobs": "getonbrd/programming.json",
            "/api/v0/categories/design-ux/jobs": "getonbrd/design.json",
            "/api/v0/companies/1339": "getonbrd/company_1339.json",
            "/api/v0/companies/77": "getonbrd/company_77.json",
        }
        return httpx.Response(200, json=load_fixture(route[req.url.path]))

    return handler


def test_search_walks_categories_dedupes_and_resolves_companies(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(GetOnBrd(), _handler(load_fixture, calls))
    assert [len(p) for p in pages] == [1, 1]  # the design list repeats the first posting
    manager, designer = pages[0][0], pages[1][0]
    assert (manager.title, manager.company, manager.location) == (
        "Engineering Manager", "Rankmi", "Chile",
    )  # fmt: skip
    assert manager.url == "https://www.getonbrd.com/jobs/engineering-manager-rankmi-santiago"
    assert manager.remote == "hybrid" and manager.description == "Lead\n\nReqs\n\nPerks"
    assert manager.posted_at is not None and manager.posted_at.year == 2026
    assert (designer.company, designer.location, designer.remote) == (
        "Acme Design", "Peru, Mexico", "remote",
    )  # fmt: skip
    assert calls.count("/api/v0/companies/1339") == 1  # looked up once per run


def test_start_page_skips_pages_already_done(search_pages, load_fixture):
    pages = search_pages(GetOnBrd(), _handler(load_fixture, []), start_page=1)
    assert [p[0].title for p in pages] == ["UX Designer"]


def test_the_task_limit_stops_the_walk(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(GetOnBrd(), _handler(load_fixture, calls), limit=1)
    assert [len(p) for p in pages] == [1]
    assert "/api/v0/categories/design-ux/jobs" not in calls


def test_a_failed_company_lookup_falls_back_to_unknown(search_pages, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/api/v0/companies/"):
            return httpx.Response(404)
        return _handler(load_fixture, [])(req)

    pages = search_pages(GetOnBrd(), handler)
    assert pages[0][0].company == "Unknown"


def test_it_is_an_opt_in_aggregator():
    assert registry()["getonbrd"].kind == "aggregator"
