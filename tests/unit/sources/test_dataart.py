from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import dataart
from linkit_all.sources.companies.dataart import DataArt, places


def handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    files = {
        "/sitemap.xml": "dataart/sitemap.xml",
        "/vacancies/sla116": "dataart/vacancy_sla116.html",
        "/vacancies/jav1526": "dataart/vacancy_jav1526.html",
    }

    def handle(req: httpx.Request) -> httpx.Response:
        name = files.get(req.url.path)
        if req.url.path == "/robots.txt" or not name:
            return httpx.Response(404)
        return httpx.Response(200, text=load_fixture(name))

    return handle


def test_sitemap_then_vacancies(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(DataArt(), handler(load_fixture), calls=calls)
    assert len(pages) == 1
    # translations, the listing root and unrelated pages are never fetched
    assert not any("/es/" in u or u.endswith("/vacancies") or "events" in u for u in calls)
    java, shopify = pages[0]  # sorted by URL
    assert shopify.title == "Shopify Solutions Architect" and shopify.company == "DataArt"
    assert shopify.url == "https://www.dataart.team/vacancies/sla116"
    assert shopify.location == "Almaty, Kazakhstan; Warsaw, Poland" and shopify.remote is None
    assert "Lead" in shopify.description and "<" not in shopify.description
    assert "script" not in shopify.description
    assert shopify.posted_at is not None and shopify.posted_at.isoformat() == "2025-05-07T00:00:00"
    assert shopify.extra["id"] == "sla116" and shopify.source == "dataart"
    # "Remote.*" codes mark the role remote and are not shown as places
    assert java.location == "Buenos Aires; Kyiv, Ukraine" and java.remote == "remote"


def test_chunks_resume_and_details(
    search_pages: Callable[..., list[list[JobStub]]],
    fetch_details: Callable[..., JobStub],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dataart, "CHUNK", 1)
    assert [len(p) for p in search_pages(DataArt(), handler(load_fixture))] == [1, 1]
    resumed = search_pages(DataArt(), handler(load_fixture), start_page=1)
    assert [s.extra["id"] for p in resumed for s in p] == ["sla116"]
    stub = JobStub(
        source="dataart",
        url="https://www.dataart.team/vacancies/jav1526",
        title="t",
        company="DataArt",
    )
    assert "Write Java." in fetch_details(DataArt(), handler(load_fixture), stub).description


def test_places() -> None:
    posting = {
        "jobLocation": [
            {"address": {"addressLocality": "Kyiv", "addressCountry": "Ukraine"}},
            {"address": {"addressLocality": "Kyiv", "addressCountry": "Ukraine"}},
            {"address": {"addressCountry": "Germany"}},
        ]
    }
    assert places(posting) == ("Kyiv, Ukraine; Germany", False)
    assert places({}) == ("", False)
