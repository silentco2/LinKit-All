import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.boards.startup_jobs import StartupJobs, title_and_company
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
    ((a, b),) = search_pages(StartupJobs(), _text(load_fixture("startup-jobs/feed.xml")))
    assert (a.title, a.company, a.location) == (
        "Platform Engineer",
        "Fernhill Robotics",
        "Berlin, Germany",
    )
    assert a.url == "https://startup.jobs/platform-engineer-fernhill-robotics-7001"
    assert "Run our clusters." in a.description
    assert (b.company, b.location, b.remote) == ("Prologix", "Remote", "remote")


def test_title_split_uses_the_last_at():
    assert title_and_company("Head of Data at Scale at Gridworks") == (
        "Head of Data at Scale",
        "Gridworks",
    )
    assert title_and_company("Engineer") is None


def test_it_is_an_opt_in_board():
    _opt_in("startup-jobs")
