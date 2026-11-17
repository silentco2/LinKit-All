import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.bulldogjob import Bulldogjob
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


def test_search_reads_the_page_data(search_pages, load_fixture):
    calls: list[str] = []
    ((a, b),) = search_pages(Bulldogjob(), _text(load_fixture("bulldogjob/page1.html"), calls))
    assert calls == ["https://bulldogjob.pl/companies/jobs/s/page,1"]  # total reached: no page 2
    assert (a.title, a.company, a.location) == (
        "Senior DevOps Engineer",
        "Wisła Cloud",
        "Remote, Kraków",
    )
    assert a.url == "https://bulldogjob.pl/companies/jobs/180001-senior-devops"
    assert a.apply_url == "https://jobs.lever.co/wislacloud/abc" and a.remote == "remote"
    assert (b.location, b.remote, b.apply_url) == ("Wrocław", None, b.url)


def test_a_page_without_its_data_fails_loudly(search_pages):
    with pytest.raises(ValueError, match="pageProps"):
        search_pages(Bulldogjob(), _text("<html></html>"))


def test_opt_in():
    assert len(_opt_in("bulldogjob")) == 1
