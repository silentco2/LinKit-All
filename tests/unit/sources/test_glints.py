import json

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.glints import Glints
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


def test_search_posts_the_pages_query(search_pages, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("glints/search.json"))

    ((a, b),) = search_pages(Glints(), handler, query="backend")
    (req,) = seen
    assert req.url == "https://glints.com/api/v2-alc/graphql"
    assert req.headers["origin"] == "https://glints.com"
    data = json.loads(req.content)["variables"]["data"]
    assert (data["SearchTerm"], data["CountryCode"], data["page"]) == ("backend", "ID", 1)
    assert (a.title, a.company, a.location) == (
        "Backend Engineer",
        "Nusantara Pay",
        "Jakarta Selatan, Indonesia",
    )
    assert a.url == "https://glints.com/id/opportunities/jobs/aaaa-1111"
    assert (b.company, b.remote) == ("Komodo Labs", "remote")


def test_graphql_errors_fail_loudly(search_pages):
    with pytest.raises(ValueError, match="errors"):
        search_pages(
            Glints(),
            lambda req: httpx.Response(200, json={"errors": [{"message": "x"}]}),
            query="x",
        )
