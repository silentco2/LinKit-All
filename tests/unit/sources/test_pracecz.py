import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.pracecz import PraceCz
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


def test_search_reads_the_page_data_stream(search_pages, load_fixture):
    calls: list[str] = []
    ((a, b),) = search_pages(
        PraceCz(), _text(load_fixture("pracecz/search.html"), calls), query="java dev"
    )
    assert calls == ["https://www.prace.cz/nabidky/?q=java%20dev"]
    assert (a.title, a.company, a.location) == (
        "Backend vývojář",
        "Beskydy Software",
        "Remote, Ostrava",
    )
    assert a.url == "https://kariera.beskydy.jobs.cz/detail/1"  # the employer's jobs.cz page
    assert (a.salary_min, a.salary_max, a.salary_currency, a.salary_interval) == (
        70000,
        90000,
        "CZK",
        "month",
    )  # monthly pay kept as stated
    assert b.url == "https://www.prace.cz/nabidka/1700000002/" and b.salary_min is None


def test_changed_markup_fails_loudly(search_pages):
    with pytest.raises(ValueError):
        search_pages(PraceCz(), _text("<html></html>"), query="x")
