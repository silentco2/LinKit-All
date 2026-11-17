import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.occ import Occ, search_url
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
    calls: list[str] = []
    ((a, b),) = search_pages(
        Occ(), _text(load_fixture("occ/search.html"), calls), query="Ingeniería de Datos"
    )
    assert calls[:2] == [
        "https://www.occ.com.mx/empleos/de-ingenieria-de-datos/",
        "https://www.occ.com.mx/empleos/de-ingenieria-de-datos-pagina-2/",
    ]
    assert (a.title, a.company, a.location) == (
        "Ingeniero de Datos",
        "Sierra Madre Analytics",
        "Monterrey, N.L.",
    )
    assert a.url == "https://www.occ.com.mx/empleo/oferta/21000001/"
    assert b.company == "Empresa confidencial"


def test_search_url():
    assert search_url("C++ dev", 3) == "https://www.occ.com.mx/empleos/de-c-dev-pagina-3/"
