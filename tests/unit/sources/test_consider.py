import json

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.ats.consider import Consider
from linkit_all.sources.ats_detector import detect
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


def test_search_reads_the_board_id_and_token_from_the_page(search_pages, load_fixture):
    sent: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.host == "jobs.founderly.example"
        if req.url.path == "/jobs":
            return httpx.Response(
                200, text=load_fixture("consider/board.html"), headers={"set-cookie": "s=1; Path=/"}
            )
        if req.url.path == "/api-boards/search-jobs":
            sent.append(req)
            return httpx.Response(200, json=load_fixture("consider/jobs.json"))
        return httpx.Response(404)

    ((a, b),) = search_pages(Consider(), handler, board="jobs.founderly.example")
    (req,) = sent
    assert req.headers["x-csrf-token"] == "tok-12345678" and "s=1" in req.headers["cookie"]
    assert json.loads(req.content)["board"] == {"id": "wingman", "isParent": True}
    assert (a.title, a.company, a.location) == (
        "Founding Engineer",
        "Tidewater",
        "Zurich, Switzerland",
    )
    assert a.ats == "ashby" and a.url == "https://jobs.ashbyhq.com/tidewater/abc"
    assert a.posted_at is not None
    assert (b.location, b.remote, b.ats) == ("London, UK", "remote", "greenhouse")


def test_shorthand():
    assert detect("consider:jobs.founderly.example") == ("consider", "jobs.founderly.example")
