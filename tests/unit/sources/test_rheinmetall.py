import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.companies.rheinmetall import Rheinmetall
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


def test_search_walks_pages_until_nothing_new(search_pages, load_fixture):
    calls: list[str] = []
    ((a, b),) = search_pages(Rheinmetall(), _text(load_fixture("rheinmetall/page1.html"), calls))
    assert calls[:2] == [
        "https://www.rheinmetall.com/en/career/vacancies?page=1",
        "https://www.rheinmetall.com/en/career/vacancies?page=2",
    ]
    assert (a.title, a.company, a.location) == (
        "Systems Engineer",
        "Rheinmetall Electronics GmbH",
        "Bremen",
    )
    assert a.url == "https://www.rheinmetall.com/en/job/systems-engineer/70001" and a.extra == {
        "id": "70001"
    }
    assert (b.company, b.location) == ("Rheinmetall AG", "Düsseldorf")
