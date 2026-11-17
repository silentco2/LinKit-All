import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.joinup import JoinUp


def _page(html):
    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text=html)
        )

    return handler


def test_search_reads_the_server_rendered_page(search_pages, load_fixture):
    ((a, b),) = search_pages(JoinUp(), _page(load_fixture("joinup/browse.html")))
    assert (a.title, a.company, a.location) == ("Robotics Engineer", "Alpenglow Robotics", "Zürich")
    assert a.url == "https://joinup.ch/job/robotics-engineer-alpenglow"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-20T10:00:00"
    assert (b.title, b.location, b.remote) == ("Growth Lead", "Remote", "remote")
    assert b.posted_at is not None and b.extra == {"id": "growth-lead-tidepool"}


def test_a_page_without_its_data_fails_loudly(search_pages):
    with pytest.raises(ValueError, match="__NEXT_DATA__"):
        search_pages(JoinUp(), _page("<html></html>"))


def test_it_is_an_opt_in_feed():
    source = registry()["joinup"]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
