import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.companies.atlassian import Atlassian
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


def test_search(search_pages, load_fixture):
    data = load_fixture("atlassian/listings.json")
    ((a, b),) = search_pages(Atlassian(), lambda req: httpx.Response(200, json=data))
    assert (a.title, a.company) == ("Senior Backend Engineer", "Atlassian")
    assert a.location == (
        "San Francisco - United States - San Francisco, California 94104 United States; Remote - United States"
    )
    assert (
        a.url == "https://careers-atlassian.icims.com/jobs/101/job"
    )  # the posting page, not the form
    assert a.apply_url.endswith("?mode=apply") and a.remote == "remote"
    assert b.url == "https://careers-atlassian.icims.com/jobs/102/job?mode=apply"


def test_opt_in():
    assert len(_opt_in("atlassian")) == 1
