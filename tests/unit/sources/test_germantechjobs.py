import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.germantechjobs import GermanTechJobs, title_and_company
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
    ((a, b),) = search_pages(GermanTechJobs(), _text(load_fixture("germantechjobs/feed.xml")))
    assert (a.title, a.company, a.location) == ("Senior Java Developer", "Spree Systems GmbH", "")
    assert a.url == "https://germantechjobs.de/jobs/Spree-Systems-GmbH-Senior-Java-Developer"
    assert a.description == "Java 21, Spring." and a.posted_at is not None
    assert (b.company, b.remote) == ("Elbe UI AG", "remote")


def test_title_split():
    assert title_and_company("Dev @ A @ B [1 €]") == ("Dev @ A", "B")
    assert title_and_company("Dev") is None
