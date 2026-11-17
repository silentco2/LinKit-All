import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.companies.deutschebahn import DeutscheBahn
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


def test_search_reads_one_large_page(search_pages, load_fixture):
    calls: list[str] = []
    ((a, b),) = search_pages(DeutscheBahn(), _text(load_fixture("deutschebahn/search.html"), calls))
    assert calls[0] == (
        "https://db.jobs/service/search/de-de/5441588"
        "?query=&sort=pubExternalDate_tdt&itemsPerPage=1000&pageNum=1"
    )
    assert (a.title, a.company, a.location) == (
        "Lokführer:in",
        "Deutsche Bahn",
        "Hamburg, Deutschland",
    )
    assert a.url == "https://db.jobs/de-de/Suche/Lokfuehrer-1180001?jobId=310001"
    assert a.extra == {"id": "310001"} and b.location == "Frankfurt (Main), Deutschland"
