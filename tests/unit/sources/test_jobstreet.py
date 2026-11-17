import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.jobstreet import Jobstreet, markets_for
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
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("jobstreet/search.json"))

    ((a, b),) = search_pages(
        Jobstreet(), handler, query="data", country="id", posted_within_days=100000
    )
    (req,) = seen
    assert req.url.host == "id.jobstreet.com" and req.url.path == "/api/jobsearch/v5/search"
    assert req.url.params["siteKey"] == "ID-Main" and req.url.params["keywords"] == "data"
    assert (a.title, a.company, a.location) == (
        "Data Analyst",
        "Merapi Retail",
        "Jakarta Selatan, Jakarta Raya",
    )
    assert a.url == "https://id.jobstreet.com/id/job/88001234" and a.remote == "hybrid"
    assert a.description == "Analyse sales data." and b.company == "Bromo Logistik"


def test_markets_follow_the_search_places():
    assert markets_for(["Singapore", "Kuala Lumpur, Malaysia"]) == ["sg", "my"]
    assert markets_for(["Berlin"]) == ["id"]
    cfg = SearchConfig.model_validate(
        {
            "search": {"queries": ["a"], "locations": ["Hong Kong"]},
            "sources": {"enabled": ["jobstreet"]},
        }
    )
    (task,) = registry()["jobstreet"].tasks(cfg)
    assert task.country == "hk"
