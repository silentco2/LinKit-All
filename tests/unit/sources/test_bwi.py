import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.companies.bwi import Bwi, slug_title
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


def test_search_lists_the_whole_board_in_one_request(search_pages, load_fixture):
    calls: list[str] = []
    ((a, b),) = search_pages(Bwi(), _text(load_fixture("bwi/list.html"), calls))
    assert calls == ["https://www.bwi.de/karriere/stellenangebote"]
    assert (a.title, a.company) == ("Security Analyst Soc (m/w/d)", "BWI GmbH")
    assert a.extra == {"id": "69624"} and b.title == "Werkstudent It"


def test_fetch_details_reads_the_posting(fetch_details, load_fixture):
    stub = Bwi().parse(load_fixture("bwi/list.html"))[0]
    full = fetch_details(Bwi(), _text(load_fixture("bwi/detail.html")), stub)
    assert (full.title, full.location, full.description) == (
        "Security Analyst SOC (m/w/d)",
        "Meckenheim",
        "Angriffe erkennen.",
    )
    assert full.posted_at.isoformat() == "2026-10-05T00:00:00"


def test_slug_title():
    assert slug_title("https://x/job/data-engineer-m-d-w-12345") == "Data Engineer (m/w/d)"
