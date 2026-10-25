import httpx

from linkit_all.sources import registry
from linkit_all.sources.aggregators.tecla import Tecla


def _handler(load_fixture, asked):
    def handler(req: httpx.Request) -> httpx.Response:
        page = req.url.params["page"]
        asked.append(page)
        return httpx.Response(200, json=load_fixture(f"tecla/page{page}.json"))

    return handler


def test_search_pages_to_the_reported_count_and_maps_postings(search_pages, load_fixture):
    asked: list[str] = []
    pages = search_pages(Tecla(), _handler(load_fixture, asked))
    assert asked == ["1", "2"] and [len(p) for p in pages] == [2, 1]
    first = pages[0][0]
    assert (first.title, first.company, first.remote) == (
        "Practice / Business Development", "Sliiip", "remote",
    )  # fmt: skip
    assert first.url == "https://app.tecla.io/job?id=3301"
    assert first.description == "Grow it"  # the script is dropped
    assert first.posted_at is not None and first.posted_at.year == 2026
    assert pages[1][0].posted_at is None  # empty createdAt


def test_resume_and_limit(search_pages, load_fixture):
    asked: list[str] = []
    search_pages(Tecla(), _handler(load_fixture, asked), start_page=1)
    assert asked == ["2"]
    asked.clear()
    search_pages(Tecla(), _handler(load_fixture, asked), limit=2)
    assert asked == ["1"]


def test_it_is_an_opt_in_aggregator():
    assert registry()["tecla"].kind == "aggregator"
