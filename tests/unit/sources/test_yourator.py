import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.yourator import Yourator
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
    data = load_fixture("yourator/jobs.json")
    ((a, b),) = search_pages(
        Yourator(), lambda req: httpx.Response(200, json=data), posted_within_days=100000
    )
    assert (a.title, a.company, a.location) == ("Frontend Engineer", "Formosa Labs", "台北市")
    assert a.url == "https://jobs.lever.co/formosa/xyz?lever-source=y"  # employer page, no utm
    assert (
        a.ats == "lever"
        and a.extra["page"] == "https://www.yourator.co/companies/formosa/jobs/41001"
    )
    assert (
        b.url == "https://www.yourator.co/companies/kaohsiung/jobs/41002" and b.remote == "remote"
    )


def test_opt_in():
    assert len(_opt_in("yourator")) == 1
