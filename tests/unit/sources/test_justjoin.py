import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.justjoin import JustJoin
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _text(body, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if calls is not None:
            calls.append(str(req.url))
        return httpx.Response(200, text=body)

    return handler


def _opt_in(name, queries=()):
    source = registry()[name]
    assert source.kind == "aggregator" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate(
        {"search": {"queries": list(queries)}, "sources": {"enabled": [name]}}
    )
    assert source.is_enabled(cfg)
    return source.tasks(cfg)


def test_search(search_pages, load_fixture):
    data = load_fixture("justjoin/offers.json")
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=data)

    ((a, b),) = search_pages(JustJoin(), handler, posted_within_days=100000)
    assert seen[0].url.path == "/api/candidate-api/offers"
    assert seen[0].url.params["from"] == "0" and seen[0].url.params["sortBy"] == "publishedAt"
    assert (a.title, a.company, a.location) == (
        "Python Developer",
        "Tatra Labs",
        "Kraków, Warszawa",
    )
    assert a.url == "https://justjoin.it/job-offer/tatra-labs-python-developer-krakow"
    assert a.remote == "hybrid" and a.posted_at.isoformat() == "2026-10-12T10:00:00"
    assert (b.remote, b.location) == ("remote", "Gdańsk")


def test_opt_in():
    assert len(_opt_in("justjoin")) == 1
