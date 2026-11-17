from datetime import datetime

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.jobscz import JobsCz, posted
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
        JobsCz(), _text(load_fixture("jobscz/search.html"), calls), query="python"
    )
    assert calls == ["https://www.jobs.cz/prace/?q%5B%5D=python"]  # 2 found: one page
    assert (a.title, a.company, a.location) == (
        "Python vývojář",
        "Vltava Data s.r.o.",
        "Praha 8 - Karlín",
    )
    assert a.url == "https://www.jobs.cz/rpd/2000111111/" and a.extra == {"id": "2000111111"}
    assert a.posted_at is not None and (a.posted_at.month, a.posted_at.day) == (10, 12)
    assert b.posted_at is not None


def test_no_results_and_changed_markup(search_pages):
    empty = "<html><body>Nenašli jsme žádné nabídky</body></html>"
    assert search_pages(JobsCz(), _text(empty), query="x") == []
    with pytest.raises(ValueError, match="markup"):
        search_pages(JobsCz(), _text("<html><body>?</body></html>"), query="x")


def test_czech_dates():
    now = datetime(2026, 3, 5, 12, 0)
    assert posted("12. října", now) == datetime(2025, 10, 12)  # not in the future: last year
    assert posted("2. března", now) == datetime(2026, 3, 2)
    assert posted("Aktualizováno před 3 hodinami", now) == datetime(2026, 3, 5, 9, 0)
    assert posted("whenever", now) is None


def test_one_task_per_query():
    assert len(_opt_in("jobscz", ["a", "b"])) == 2
