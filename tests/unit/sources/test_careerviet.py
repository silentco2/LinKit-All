from datetime import datetime

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.aggregators.careerviet import CareerViet, list_url, updated
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


def test_search(search_pages, load_fixture):
    calls: list[str] = []
    ((a, b),) = search_pages(
        CareerViet(), _text(load_fixture("careerviet/list.html"), calls), query="data engineer"
    )
    assert calls[:2] == [
        "https://careerviet.vn/viec-lam/data-engineer-k-vi.html",
        "https://careerviet.vn/viec-lam/data-engineer-k-trang-2-vi.html",
    ]
    assert (a.title, a.company, a.location) == ("Kỹ sư dữ liệu", "Công ty Sông Hồng", "Hồ Chí Minh")
    assert a.url == "https://careerviet.vn/vi/tim-viec-lam/ky-su-du-lieu.35B1A2C3.html"
    assert a.posted_at == datetime(2026, 10, 11, 17, 0)  # midnight in Vietnam, as UTC
    assert b.extra == {"id": "35B1A2C4"}


def test_urls_and_dates():
    assert list_url("", 1) == "https://careerviet.vn/viec-lam/tat-ca-viec-lam-vi.html"
    assert updated("31-02-2026") is None
