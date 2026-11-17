import json

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.tes import Tes, pay
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


def test_search_sends_the_pages_own_query(search_pages, load_fixture):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("tes/search.json"))

    ((a, b),) = search_pages(Tes(), handler, query="maths", posted_within_days=100000)
    query = json.loads(seen[0].url.params["input"])["0"]["json"]
    assert query["filters"]["keywords"] == "maths" and query["limit"] == 50
    assert query["filters"]["sort"] == "date" and query["siteCountry"] == "gb"
    assert (a.title, a.company, a.location) == (
        "Teacher of Maths",
        "Larkfield Academy",
        "Leeds, West Yorkshire",
    )
    assert a.url == "https://www.tes.com/jobs/vacancy/teacher-of-maths-1300001"
    assert (a.salary_min, a.salary_max, a.salary_currency) == (31650, 49084, "GBP")
    assert a.description == "Join our maths team." and b.salary_min is None


def test_an_error_answer_fails_loudly(search_pages):
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"error": {"json": {"message": "bad"}}}])

    with pytest.raises(ValueError, match="error"):
        search_pages(Tes(), handler, query="x")


def test_pay():
    assert pay("€30,000 per annum") == (30000, 30000, "EUR")
    assert pay("£1 - €2 per year") is None and pay("Competitive") is None
