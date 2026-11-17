import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.boards.higheredjobs import HigherEdJobs, split_org
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _text(body):
    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text=body)
        )

    return handler


def _opt_in(name):
    source = registry()[name]
    assert not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate({"sources": {"enabled": [name]}})
    assert source.is_enabled(cfg) and len(source.tasks(cfg)) == 1


def test_search(search_pages, load_fixture):
    calls: list[str] = []
    ((a, b),) = search_pages(
        HigherEdJobs(), _text(load_fixture("higheredjobs/feed.xml")), calls=calls
    )
    assert calls[-1] == "https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=68"
    assert (a.title, a.company, a.location) == (
        "Assistant Professor of Biology",
        "Lakeshore State University",
        "Duluth, MN",
    )
    assert a.extra == {"id": "178000001"} and a.posted_at is not None
    assert (b.company, b.location) == ("Pinecrest College", "")


def test_a_bot_wall_is_an_error_not_an_empty_board(search_pages):
    with pytest.raises(ValueError, match="not a feed"):
        search_pages(HigherEdJobs(), _text("<html><script>challenge()</script></html>"))


def test_split_org():
    assert split_org("A (B) College (Ames, IA)") == ("A (B) College", "Ames, IA")


def test_it_is_an_opt_in_board():
    _opt_in("higheredjobs")
