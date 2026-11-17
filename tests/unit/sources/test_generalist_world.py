import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.boards.generalist_world import GeneralistWorld
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
    ((a, b),) = search_pages(GeneralistWorld(), _text(load_fixture("generalist-world/jobs.html")))
    assert (a.title, a.company, a.location) == ("Chief of Staff", "Quarry Labs", "Remote (UK)")
    assert a.url == "https://generalist.world/jobs/chief-of-staff-quarry/"
    assert a.description == "Work with the CEO." and a.remote == "remote"
    assert a.extra == {"id": "chief-of-staff-quarry", "salary_text": "£70k\u2013£85k"}
    assert (b.title, b.location) == ("Founder's Associate", "Europe")  # region fallback


def test_a_page_without_the_list_fails_loudly(search_pages):
    with pytest.raises(ValueError, match="no job list"):
        search_pages(GeneralistWorld(), _text("<html></html>"))


def test_it_is_an_opt_in_board():
    _opt_in("generalist-world")
