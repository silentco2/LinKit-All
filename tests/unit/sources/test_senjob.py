import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.senjob import Senjob
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


def test_search_reads_rows_and_their_hidden_dates(search_pages, load_fixture):
    html = load_fixture("senjob/list.html")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=html if "page" not in req.url.params else "<table></table>")

    ((a, b),) = search_pages(Senjob(), handler, posted_within_days=100000)
    assert (a.title, a.location, a.company) == ("Comptable confirmé", "Dakar", "")
    assert a.url == "https://senjob.com/jobseekers/comptable-confirme_e_90001.html"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-12T00:00:00"
    assert (b.title, b.location, b.extra) == ("Développeur web", "Thiès", {"id": "90002"})


def test_fetch_details_names_the_employer(fetch_details, load_fixture):
    stub = Senjob().rows(load_fixture("senjob/list.html"))[0]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture("senjob/detail.html"))

    full = fetch_details(Senjob(), handler, stub)
    assert (full.company, full.description) == ("Teranga Finance", "Tenir la comptabilité.")
