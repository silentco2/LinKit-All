from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import herp
from linkit_all.sources.ats.herp import Herp
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def _handler(load_fixture: Callable[[str], Any], calls: list[str]) -> Any:
    pages = {
        "/v1/acme": "herp/board.html",
        "/v1/acme/requisition-groups/g1": "herp/group.html",
        "/v1/acme/job1": "herp/job1.html",
        "/v1/acme/job2": "herp/job2.html",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(req.url.path)
        return httpx.Response(200, text=load_fixture(pages[req.url.path]))

    return handler


def test_listing_groups_and_job_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Herp(), _handler(load_fixture, calls), board="acme")
    # The board page, then its one requisition group, then each job once. The /apply, "top",
    # other-board and share-widget links are not jobs.
    assert calls == [
        "/v1/acme",
        "/v1/acme/requisition-groups/g1",
        "/v1/acme/job1",
        "/v1/acme/job2",
    ]
    assert len(pages) == 1
    job1, job2 = pages[0]
    assert job1.title == "Backend Engineer" and job1.location == "Tokyo"
    assert job1.url == "https://herp.careers/v1/acme/job1"
    assert job1.company == "Acme"  # no hiringOrganization: from the slug
    assert job1.description == "Build things."
    assert job1.posted_at is not None and job1.posted_at.date().isoformat() == "2025-04-18"
    assert job1.extra["id"] == "job1" and job1.extra["board"] == "acme" and job1.ats == "herp"
    assert job2.title == "Frontend Engineer" and job2.company == "Acme KK"  # the page's own name


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(herp, "CHUNK", 1)
    pages = search_pages(Herp(), _handler(load_fixture, []), board="acme")
    assert [[s.title for s in p] for p in pages] == [["Backend Engineer"], ["Frontend Engineer"]]
    calls: list[str] = []
    pages = search_pages(Herp(), _handler(load_fixture, calls), board="acme", start_page=1)
    assert [[s.title for s in p] for p in pages] == [["Frontend Engineer"]]
    assert "/v1/acme/job1" not in calls


def test_a_vanished_job_page_is_skipped(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    inner = _handler(load_fixture, [])

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404) if req.url.path.endswith("job2") else inner(req)

    pages = search_pages(Herp(), handler, board="acme")
    assert [s.title for s in pages[0]] == ["Backend Engineer"]


def test_url_patterns() -> None:
    assert detect("https://herp.careers/v1/a244/GnoQonoXGBZi") == ("herp", "a244")
