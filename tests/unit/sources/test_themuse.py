import httpx
import pytest

from linkit_all.sources import registry
from linkit_all.sources.aggregators.themuse import TheMuse


def test_search_pages_and_maps_postings(search_pages, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=load_fixture(f"themuse/page{req.url.params['page']}.json"))

    pages = search_pages(TheMuse(), handler)
    assert [len(p) for p in pages] == [1, 1]  # the posting without an id is dropped
    senior, junior = pages[0][0], pages[1][0]
    assert (senior.title, senior.company, senior.location) == (
        "Senior Specialist Electrical Engineer", "L3Harris Technologies", "Anaheim, CA",
    )  # fmt: skip
    assert senior.url == "https://www.themuse.com/jobs/acme/senior-ee"
    assert senior.description == "Build." and senior.posted_at is not None
    assert junior.remote == "remote"


def test_a_400_past_the_real_ceiling_keeps_what_was_read(search_pages, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.params["page"] == "1":
            return httpx.Response(200, json={**load_fixture("themuse/page1.json"), "page_count": 9})
        return httpx.Response(400, json={"error": "Value `page` is too high"})

    assert [len(p) for p in search_pages(TheMuse(), handler)] == [1]


def test_a_failing_first_page_is_an_error(search_pages):
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(TheMuse(), lambda req: httpx.Response(400))


def test_it_is_an_opt_in_aggregator():
    assert registry()["themuse"].kind == "aggregator"
