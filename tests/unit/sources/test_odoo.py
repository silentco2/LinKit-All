from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import odoo
from linkit_all.sources.ats.odoo import Odoo
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

HOST = "jobs.amewaregroup.com"


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        assert req.url.host == HOST
        if path == "/jobs":
            return httpx.Response(200, text=load_fixture("odoo/listing.html"))
        if path == "/jobs/detail/recruiter-157":
            return httpx.Response(200, text=load_fixture("odoo/detail.html"))
        if path == "/en_US/jobs/detail/full-stack-python-developer-1":
            return httpx.Response(200, text=load_fixture("odoo/detail_remote.html"))
        if path == "/jobs/detail/bare-2":
            return httpx.Response(200, text=load_fixture("odoo/bare.html"))
        return httpx.Response(404)

    return handler


def test_listing_then_details(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Odoo(), make_handler(load_fixture), board=HOST, calls=calls)
    assert len(pages) == 1
    first, second = pages[0]  # the page with no microdata is dropped
    assert first.title == "Recruiter" and first.company == "Amewaregroup"
    assert first.url == f"https://{HOST}/jobs/detail/recruiter-157"
    assert first.location == "Kyiv, Ukraine" and first.ats == "odoo"
    assert "Build things" in first.description and "alert" not in first.description
    assert first.posted_at is not None and first.posted_at.isoformat().startswith("2026-07-10")
    assert first.extra == {"board": HOST, "id": "157"}
    assert second.title == "Python Developer (Remote)" and second.remote == "remote"
    assert second.url == f"https://{HOST}/en_US/jobs/detail/full-stack-python-developer-1"
    assert second.posted_at is not None and second.posted_at.hour == 8
    # filter links, the listing itself and another host's postings are never fetched
    assert not any("country" in c or "elsewhere" in c for c in calls)


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(odoo, "CHUNK", 1)
    handler = make_handler(load_fixture)
    assert len(search_pages(Odoo(), handler, board=HOST)) == 3
    resumed = search_pages(Odoo(), handler, board=HOST, start_page=1)
    assert [j.title for p in resumed for j in p] == ["Python Developer (Remote)"]


def test_bad_board_and_listing_error(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="not a careers host"):
        search_pages(Odoo(), lambda r: httpx.Response(200), board="acme")

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if req.url.path == "/robots.txt" else httpx.Response(500)

    with pytest.raises(Exception):  # noqa: B017 - any HTTP error reaches the runner
        search_pages(Odoo(), handler, board=HOST)


def test_shorthand_detects() -> None:
    assert detect(f"odoo:{HOST}") == ("odoo", HOST)
