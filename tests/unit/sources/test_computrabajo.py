import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.computrabajo import Computrabajo
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


def test_search_is_light_and_stops_on_a_repeated_page(search_pages, load_fixture):
    calls: list[str] = []
    ((a, b),) = search_pages(
        Computrabajo(), _text(load_fixture("computrabajo/search.html"), calls), query="Sistemas"
    )
    assert calls == [
        "https://co.computrabajo.com/trabajo-de-sistemas",
        "https://co.computrabajo.com/trabajo-de-sistemas?p=2",
    ]
    assert (a.title, a.company, a.location) == (
        "Analista de sistemas",
        "Andes Software SAS",
        "Bogotá, D.C.",
    )
    assert (
        a.url
        == "https://co.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-analista-de-sistemas-AB12CD"
    )
    assert a.extra == {"id": "AB12CD"} and b.location == "Barranquilla, Atlántico"


def test_a_bot_check_is_reported_not_answered(search_pages):
    page = "<html><head><title>Just a moment...</title></head></html>"
    with pytest.raises(ValueError, match="bot check"):
        search_pages(Computrabajo(), _text(page), query="x")
