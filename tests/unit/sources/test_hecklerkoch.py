import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.companies.hecklerkoch import HecklerKoch
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
    ((a, b),) = search_pages(HecklerKoch(), _text(load_fixture("hecklerkoch/list.html")))
    assert (a.title, a.company, a.location) == (
        "Zerspanungsmechaniker (m/w/d)",
        "Heckler & Koch",
        "",
    )
    assert a.url == "https://karriere.heckler-koch.com/jobposting/a1b2c3"
    assert (
        a.extra == {"id": "a1b2c3", "field": "Fertigung | Vollzeit"}
        and b.title == "SAP Berater (m/w/d)"
    )


def test_opt_in():
    assert len(_opt_in("hecklerkoch")) == 1
