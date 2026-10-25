import httpx
import pytest

from linkit_all.sources import registry
from linkit_all.sources.aggregators import golangjobs
from linkit_all.sources.aggregators.golangjobs import GolangJobs

PAGE_HTML = (
    '<html><head><script type="module" src="/assets/index-AbC123.js"></script></head></html>'
)
BUNDLE = 'x=new vn("https://mvjyjzestmcxxmmmakec.supabase.co","eyJTEST.eyJTEST.TEST");y()'


def _handler(rows, calls=None, bundle=BUNDLE):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "www.golangjobs.tech":
            if req.url.path == "/":
                return httpx.Response(200, text=PAGE_HTML)
            return httpx.Response(200, text=bundle)
        assert req.headers["apikey"] == "eyJTEST.eyJTEST.TEST"
        assert req.headers["Authorization"] == "Bearer eyJTEST.eyJTEST.TEST"
        q = req.url.params
        assert q["is_archived"] == "eq.false" and q["posted_at"].startswith("gte.")
        if calls is not None:
            calls.append(int(q["offset"]))
        off, size = int(q["offset"]), int(q["limit"])
        return httpx.Response(200, json=rows[off : off + size])

    return handler


def test_search_maps_rows(search_pages, load_fixture):
    pages = search_pages(GolangJobs(), _handler(load_fixture("golangjobs/jobs.json")))
    stubs = {s.extra["id"][:8]: s for p in pages for s in p}
    assert len(stubs) == 9
    first = stubs["0d9933eb"]
    assert (first.title, first.company, first.location) == (
        "Senior Go Engineer", "Rubix Network", "Hyderabad, India",
    )  # fmt: skip
    assert (
        first.url == "https://www.golangjobs.tech/golang-jobs/golang-jobs-at-rubix-network-0d9933eb"
    )
    assert first.apply_url.startswith("https://www.linkedin.com/posts/")
    assert first.salary_min is None and first.salary_currency is None  # USD is only a default
    assert "Rubix" in first.description and first.posted_at is not None
    paid = stubs["1454bf7a"]
    assert (paid.salary_min, paid.salary_max, paid.salary_currency, paid.salary_interval) == (
        220000, 280000, "USD", "year",
    )  # fmt: skip
    assert (stubs["cc26513b"].location, stubs["cc26513b"].remote) == ("Remote, India", "remote")
    assert (stubs["f0aa72be"].location, stubs["f0aa72be"].remote) == ("Remote", "remote")


def test_search_pages_by_offset_and_stops_on_a_short_page(search_pages, load_fixture, monkeypatch):
    monkeypatch.setattr(golangjobs, "PAGE", 4)
    calls: list[int] = []
    pages = search_pages(
        GolangJobs(), _handler(load_fixture("golangjobs/jobs.json"), calls), limit=400
    )
    assert [len(p) for p in pages] == [4, 4, 1] and calls == [0, 4, 8]
    resumed = search_pages(
        GolangJobs(), _handler(load_fixture("golangjobs/jobs.json")), limit=400, start_page=2
    )
    assert [len(p) for p in resumed] == [1]


def test_the_task_limit_caps_the_pages(search_pages, load_fixture, monkeypatch):
    monkeypatch.setattr(golangjobs, "PAGE", 4)
    calls: list[int] = []
    search_pages(GolangJobs(), _handler(load_fixture("golangjobs/jobs.json"), calls), limit=8)
    assert calls == [0, 4]


def test_a_bundle_without_the_client_fails_by_name(search_pages):
    with pytest.raises(ValueError, match="no Supabase client"):
        search_pages(GolangJobs(), _handler([], bundle="var d={}"))


def test_it_is_an_opt_in_aggregator():
    assert registry()["golangjobs"].kind == "aggregator"
