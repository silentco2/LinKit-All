import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.jobbankca import JobBankCa
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


def test_search_reads_the_atom_feed(search_pages, load_fixture):
    calls: list[str] = []
    ((a, b),) = search_pages(
        JobBankCa(), _text(load_fixture("jobbankca/feed.xml"), calls), query="software"
    )
    assert calls == [
        "https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed?searchstring=software&locationstring=&page=1"
    ]  # a short page ends the walk
    assert (a.title, a.company, a.location) == (
        "software engineer",
        "Maple Grove Tech Inc.",
        "Halifax (NS)",
    )
    assert a.url == "https://www.jobbank.gc.ca/jobsearch/jobposting/44000001"
    assert a.extra == {"id": "44000001"} and "$45.00 hourly" in a.description
    assert (b.company, b.location) == ("Prairie Code Ltd", "Regina (SK)")


def test_an_empty_page_ends_the_search(search_pages):
    assert (
        search_pages(JobBankCa(), _text('<feed xmlns="http://www.w3.org/2005/Atom"/>'), query="x")
        == []
    )
