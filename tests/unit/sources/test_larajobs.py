import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.boards.larajobs import LaraJobs
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
    ((a, b),) = search_pages(LaraJobs(), _text(load_fixture("larajobs/feed.xml")))
    assert (a.title, a.company, a.location) == (
        "Senior Laravel Developer",
        "Copperleaf Apps",
        "Remote",
    )
    assert a.url == "https://larajobs.com/job/3001" and a.remote == "remote"
    assert a.description == "Build & maintain apps."
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-12T14:00:00"
    assert a.extra == {"id": "https://larajobs.com/job/3001"}
    assert (b.company, b.location, b.extra) == ("Harbor & Co", "Lisbon, Portugal", {"id": "3002"})


def test_it_is_an_opt_in_board():
    _opt_in("larajobs")
