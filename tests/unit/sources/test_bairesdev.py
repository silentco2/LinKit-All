from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.bairesdev import BairesDev, parse_listing


def handler(
    load_fixture: Callable[[str], Any], full_text: bool = True
) -> Callable[[httpx.Request], httpx.Response]:
    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.host == "talent.bairesdev.com" and req.url.path == "/":
            return httpx.Response(200, text=load_fixture("bairesdev/talent.html"))
        if req.url.path == "/api/JobPosting":
            jid = req.url.params["JobPostingId"]
            return httpx.Response(200, json=load_fixture(f"bairesdev/posting_{jid}.json"))
        if req.url.path == "/api/Job" and full_text and req.url.params["JobOfferId"] == "284579":
            return httpx.Response(200, json=load_fixture("bairesdev/job_284579.json"))
        return httpx.Response(404)

    return handle


def test_listing_dedupes_by_job_id(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(BairesDev(), handler(load_fixture))
    assert len(pages) == 1 and len(pages[0]) == 2  # one role listed per location; bad link dropped
    sales, node = pages[0]
    assert sales.title == "Sales Director" and sales.company == "BairesDev"
    assert sales.url == "https://applicants.bairesdev.com/job/97/284579/apply"
    assert sales.location == "New York, United States, Brazil" and sales.remote == "remote"
    assert sales.extra == {"id": "284579", "career": "97"} and sales.source == "bairesdev"
    assert node.location == "Colombia"
    assert search_pages(BairesDev(), handler(load_fixture), start_page=1) == []


def test_fetch_details_full_text(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = parse_listing(load_fixture("bairesdev/talent.html"))[0]
    out = fetch_details(BairesDev(), handler(load_fixture), stub)
    assert "The full role text." in out.description and "evil" not in out.description
    assert "Short teaser" not in out.description
    assert out.posted_at is not None and out.posted_at.isoformat().startswith("2025-06-02")


def test_fetch_details_falls_back_to_the_teaser(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    node = parse_listing(load_fixture("bairesdev/talent.html"))[1]  # no Job-endpoint text
    out = fetch_details(BairesDev(), handler(load_fixture), node)
    assert out.description == "Build it."
    assert out.posted_at is not None and out.posted_at.year == 2022


def test_no_widget_is_an_error() -> None:
    with pytest.raises(ValueError, match="widget"):
        parse_listing("<html></html>")
    with pytest.raises(ValueError, match="widget"):
        parse_listing('<div data-widget-config="bm90IGpzb24="></div>')
