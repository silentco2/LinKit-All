import json

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.companies.aldi_nord import AldiNord, place
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


def test_search_reads_the_covering_page(search_pages, load_fixture):
    pages: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert str(req.url) == "https://www.aldi-nord.de/api/job/hr/query"
        body = json.loads(req.content)
        assert body["locale"] == "de-DE"
        pages.append(body["page"])
        return httpx.Response(200, json=load_fixture(f"aldi-nord/page{body['page']}.json"))

    ((a, b),) = search_pages(AldiNord(), handler, board="www.aldi-nord.de", location="de-DE")
    assert pages == [1, 2]  # page 1 for the total, then the page that covers 12 rows
    assert (a.title, a.company, a.location) == (
        "Filialleiter (m/w/d)",
        "ALDI Nord",
        "Essen / Dortmund, Deutschland",
    )
    assert a.url == "https://www.aldi-nord.de/karriere/detail/filialleiter-m-w-d-1001.html"
    assert b.location == "Kiel, Deutschland; Venlo, Nederland"


def test_one_task_per_locale():
    tasks = _opt_in("aldi-nord")
    assert len(tasks) == 9 and {(t.board, t.location) for t in tasks} >= {("www.aldi.be", "fr-BE")}


def test_place():
    assert place([{"city": "", "country": ""}, "x"]) == ""
