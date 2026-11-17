import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.boards.fourdayweek import FourDayWeek
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
    data = load_fixture("4dayweek/jobs.json")
    calls: list[str] = []
    ((a, b),) = search_pages(
        FourDayWeek(),
        lambda req: httpx.Response(200, json=data),
        calls=calls,
        posted_within_days=100000,
    )
    assert calls == ["https://4dayweek.io/api/jobs?page=1"]
    assert (a.title, a.company, a.location) == (
        "Product Designer",
        "Lumen Studio",
        "United Kingdom",
    )
    assert a.url == "https://4dayweek.io/job/product-designer-lumen" and a.remote == "remote"
    assert a.posted_at is not None and a.extra == {"id": "901"}
    assert (b.company, b.location, b.remote) == ("Oakline", "Bristol, United Kingdom", None)


def test_it_is_an_opt_in_board():
    _opt_in("4dayweek")
