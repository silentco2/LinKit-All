import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.boards.agentic_jobs import AgenticJobs
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _text(body):
    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(200, text=body)
        )

    return handler


def _opt_in(name):
    source = registry()[name]
    assert not source.is_enabled(SearchConfig())
    cfg = SearchConfig.model_validate({"sources": {"enabled": [name]}})
    assert source.is_enabled(cfg) and len(source.tasks(cfg)) == 1


def test_search(search_pages, load_fixture):
    data = load_fixture("agentic-jobs/jobs.json")
    calls: list[str] = []
    ((a, b),) = search_pages(
        AgenticJobs(),
        lambda req: httpx.Response(200, json=data),
        calls=calls,
        posted_within_days=100000,
    )
    assert calls == ["https://agentic-engineering-jobs.com/api/v1/jobs?page=1"]
    assert (a.title, a.company, a.location) == (
        "Agent Platform Engineer",
        "Brightloop AI",
        "Remote (EU)",
    )
    assert a.url == "https://agentic-engineering-jobs.com/jobs/agent-platform-engineer-brightloop"
    assert a.description == "Ship agents." and a.remote == "remote"
    assert (a.salary_min, a.salary_max, a.salary_currency) == (90000, 120000, "EUR")
    assert b.location == "IN" and b.salary_min is None  # no place: the country codes


def test_it_is_an_opt_in_board():
    _opt_in("agentic-jobs")
