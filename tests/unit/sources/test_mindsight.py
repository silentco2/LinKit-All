from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.mindsight import Mindsight
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def fast_limiter(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))
    yield


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/acme":
            return httpx.Response(200, text=load_fixture("mindsight/listing.html"))
        if path == "/acme/9001":
            return httpx.Response(200, text=load_fixture("mindsight/detail_9001.html"))
        return httpx.Response(500)  # the other postings' pages are unreadable right now

    return handler


def test_listing_then_detail_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Mindsight(), make_handler(load_fixture), board="acme")
    assert len(pages) == 1
    assert [j.title for j in pages[0]] == [  # the closed posting is skipped
        "Desenvolvedor Backend",
        "Analista de Dados",
        "Designer",
    ]
    a, b, c = pages[0]
    assert a.url == "https://oportunidades.mindsight.com.br/acme/9001" and a.company == "Acme"
    assert a.location == "Sao Paulo, SP, BR" and a.remote == "remote" and a.ats == "mindsight"
    assert a.description == "Construa APIs."
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-09-10T12:00:00"
    assert a.extra == {"board": "acme", "id": "9001"}
    # an unreadable page only costs the description; an unusable start date falls back to created_at
    assert b.description == "" and b.remote == "hybrid"
    assert b.posted_at is not None and b.posted_at.isoformat() == "2026-09-02T12:00:00"
    assert c.remote == "onsite" and c.posted_at is None


def test_resume_skips_earlier_chunks(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(Mindsight(), make_handler(load_fixture), board="acme", start_page=1) == []


def test_page_without_postings_is_an_error(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, text="<html><body>no data</body></html>")

    with pytest.raises(ValueError, match="no postings"):
        search_pages(Mindsight(), handler, board="acme")


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="mindsight",
        url="https://oportunidades.mindsight.com.br/acme/9001",
        title="t",
        company="c",
    )
    assert fetch_details(Mindsight(), make_handler(load_fixture), stub).description == (
        "Construa APIs."
    )


def test_url_patterns() -> None:
    assert detect("https://oportunidades.mindsight.com.br/acme") == ("mindsight", "acme")
    assert detect("https://oportunidades.mindsight.com.br/acme/9001") == ("mindsight", "acme")
    assert detect("mindsight:acme") == ("mindsight", "acme")
