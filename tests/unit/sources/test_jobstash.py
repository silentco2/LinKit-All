import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.jobstash import JobStash


def _handler(load_fixture, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        page = req.url.params["page"]
        if calls is not None:
            calls.append(page)
        return httpx.Response(200, json=load_fixture(f"jobstash/page{page}.json"))

    return handler


def test_search_pages_and_maps(search_pages, load_fixture):
    calls: list[str] = []
    pages = search_pages(JobStash(), _handler(load_fixture, calls), limit=400)
    assert calls == ["1", "2"] and [len(p) for p in pages] == [2, 1]
    public, gated = pages[0]
    assert (public.title, public.company, public.location) == (
        "Associate Tech Lead", "KAST", "Remote",
    )  # fmt: skip
    assert public.apply_url == "https://kastcard.pinpointhq.com/en/postings/abc"
    assert public.url == "https://jobstash.xyz/jobs/Z2IGg7/details" and public.remote == "hybrid"
    assert "Build things.\n\nResponsibilities\n- Design back-end components" in public.description
    assert "Requirements\n- 6+ years experience" in public.description
    assert public.posted_at is not None and public.posted_at.year == 2026
    assert gated.apply_url == gated.url and gated.remote == "remote"  # no gated apply link


def test_the_task_limit_and_start_page(search_pages, load_fixture):
    calls: list[str] = []
    search_pages(JobStash(), _handler(load_fixture, calls), limit=200)
    assert calls == ["1"]
    pages = search_pages(JobStash(), _handler(load_fixture), limit=400, start_page=1)
    assert [p[0].company for p in pages] == ["Acme"]


def test_it_is_an_opt_in_aggregator():
    assert registry()["jobstash"].kind == "aggregator"
