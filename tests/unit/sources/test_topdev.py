from datetime import datetime

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.topdev import TopDev, age
from linkit_all.sources.browser_extract import Capture, Challenge
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


def test_search_opens_the_page_in_the_browser(search_pages, load_fixture, monkeypatch):
    opened: list[str] = []
    source = TopDev()

    async def capture(http, url):
        opened.append(url)
        return Capture(url, load_fixture("topdev/search.html"))

    monkeypatch.setattr(source.browser, "capture", capture)
    ((a, b),) = search_pages(
        source, lambda req: httpx.Response(404), query="golang", location="HCM"
    )
    assert opened[:2] == [
        "https://topdev.vn/jobs/search?keyword=golang&page=1&region_ids=79",
        "https://topdev.vn/jobs/search?keyword=golang&page=2&region_ids=79",
    ]  # page 2 brought nothing new
    assert (a.title, a.company, a.location) == (
        "Senior Golang Developer",
        "Saigon Cloud JSC",
        "Hồ Chí Minh",
    )
    assert a.url == "https://topdev.vn/detail-jobs/senior-golang-developer-saigon-cloud-2034567"
    assert a.extra == {"id": "2034567", "level": "Senior"} and a.posted_at is not None
    assert b.remote == "remote"


def test_a_challenge_stops_the_search(search_pages, monkeypatch):
    source = TopDev()

    async def blocked(http, url):
        raise Challenge("challenge")

    monkeypatch.setattr(source.browser, "capture", blocked)
    with pytest.raises(Challenge):
        search_pages(source, lambda req: httpx.Response(404), query="x")


def test_relative_ages():
    now = datetime(2026, 10, 15, 12, 0)
    assert age("3 ngày trước", now) == datetime(2026, 10, 12, 12, 0)
    assert age("2 hours ago", now) == datetime(2026, 10, 15, 10, 0)
    assert age("1 tháng trước", now) == datetime(2026, 9, 15, 12, 0)
    assert age("vừa xong", now) == now and age("soon", now) is None
