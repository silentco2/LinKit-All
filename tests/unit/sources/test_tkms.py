import json

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.companies.tkms import Tkms
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


def _opt_in(name):
    source = registry()[name]
    assert source.kind == "company" and not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate({"sources": {"enabled": [name]}})
    assert source.is_enabled(cfg)
    return source.tasks(cfg)


def test_search(search_pages, load_fixture):
    bodies: list[dict] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=load_fixture("tkms/page0.json"))

    ((a, b),) = search_pages(Tkms(), handler)
    assert bodies == [
        {"searchQuery": "", "filter": {}, "subclient": "tkms", "locale": "en", "page": 0}
    ]
    assert (a.title, a.company, a.location) == (
        "R&D Engineer Sonar",
        "TKMS GmbH",
        "Kiel, SH / Wismar",
    )
    assert a.url == "https://jobs.tkmsgroup.com/en/job/r-d-engineer-sonar/9001"
    assert a.posted_at.isoformat() == "2026-07-02T22:00:00"
    assert (b.company, b.location) == (
        "thyssenkrupp Marine Systems",
        "Kiel, Germany",
    ) and b.posted_at
