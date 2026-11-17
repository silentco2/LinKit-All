import json

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.techinasia import TechInAsia
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


def test_search_finds_the_key_and_reads_the_whole_index(search_pages, load_fixture):
    posts: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/jobs/search":
            return httpx.Response(200, text=load_fixture("techinasia/search.html"))
        if req.url.path == "/assets/v5/app.0a1b2c3d.js":
            return httpx.Response(200, text=load_fixture("techinasia/app.js"))
        assert req.url.host == "tia1234xyz-dsn.algolia.net"
        posts.append(req)
        return httpx.Response(200, json=load_fixture("techinasia/hits.json"))

    ((a, b, c, d),) = search_pages(TechInAsia(), handler)
    (req,) = posts
    assert req.url.params["x-algolia-api-key"] == "abcdef0123456789abcdef01"
    assert req.headers["referer"] == "https://www.techinasia.com/"
    params = json.loads(req.content)["requests"][0]["params"]
    assert "country" not in params and "page=0" in params
    assert (a.title, a.company, a.location) == (
        "Growth Marketer",
        "Kopi Labs",
        "Jakarta, Indonesia",
    )
    assert a.url == "https://jobs.lever.co/kopilabs/1" and a.description == "Grow users."
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-10-14T03:00:00"
    # one intake form shared by two roles, and a shortener: the posting page is the address
    assert (b.url, c.url) == (
        "https://www.techinasia.com/jobs/a-2",
        "https://www.techinasia.com/jobs/a-3",
    )
    assert b.location == "Singapore, Remote" and b.remote == "remote"
    assert d.url == "https://www.techinasia.com/jobs/a-4"


def test_it_is_an_opt_in_feed():
    _opt_in("techinasia")
