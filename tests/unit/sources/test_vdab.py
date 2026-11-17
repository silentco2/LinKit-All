import json

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.vdab import Vdab
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


KEY = "0a0b0c0d-1111-2222-3333-444455556666"


def _serve(load_fixture, searches):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/vindeenjob/vacatures":
            return httpx.Response(200, text=load_fixture("vdab/app.html"))
        if req.url.path == "/webapps/vindeenjob/main-abc123.js":
            return httpx.Response(200, text=load_fixture("vdab/main.js"))
        if req.url.path.endswith("/vacatureLight/zoek"):
            searches.append(req)
            if req.headers.get("vej-key-monitor") != KEY:
                return httpx.Response(403)
            return httpx.Response(200, json=load_fixture("vdab/zoek.json"))
        assert req.url.path == "/rest/vindeenjob/v4/vacatures/70123456"
        assert req.headers["vej-key-monitor"] == KEY
        return httpx.Response(
            200, json={"functie": {"omschrijving": {"markdown": "Bouw pipelines."}}}
        )

    return handler


def test_search_reads_the_sites_key_then_searches(search_pages, load_fixture):
    searches: list[httpx.Request] = []
    ((a, b),) = search_pages(
        Vdab(), _serve(load_fixture, searches), query="data", posted_within_days=14
    )
    body = json.loads(searches[0].content)
    assert body["criteria"]["trefwoord"] == "data" and body["criteria"]["onlineSindsCode"] == "14"
    assert body["pagina"] == 0 and body["paginaGrootte"] == 100
    assert (a.title, a.company, a.location) == ("Data Engineer", "Schelde Analytics", "Gent")
    assert a.url == "https://www.vdab.be/vindeenjob/vacatures/70123456"
    assert a.posted_at is not None and b.posted_at is None


def test_fetch_details(fetch_details, load_fixture):
    from linkit_all.sources.base import JobStub

    bare = JobStub(
        source="vdab",
        url="https://www.vdab.be/vindeenjob/vacatures/70123456",
        title="t",
        company="c",
    )
    assert fetch_details(Vdab(), _serve(load_fixture, []), bare).description == "Bouw pipelines."
