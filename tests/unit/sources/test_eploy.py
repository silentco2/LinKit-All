from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import eploy
from linkit_all.sources.ats.eploy import Eploy
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

HOST = "careers.pei.group"


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/live-jobs.xml":
            assert req.url.host == HOST
            return httpx.Response(200, text=load_fixture("eploy/live_jobs.xml"))
        if path.startswith("/vacancies/442/"):
            return httpx.Response(200, text=load_fixture("eploy/vacancy.html"))
        if path.startswith("/vacancies/470/"):  # answers 200 with the "not found" page
            return httpx.Response(200, text=load_fixture("eploy/not_found.html"))
        return httpx.Response(410)  # 482 is gone

    return handler


def test_sitemap_then_vacancies(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Eploy(), make_handler(load_fixture), board=HOST, calls=calls)
    assert len(pages) == 1 and len(pages[0]) == 1  # not-found and gone vacancies are dropped
    job = pages[0][0]
    assert job.title == "Senior Reporter - Private Equity" and job.company == "PEI Group"
    # The branded site's sitemap names the tenant's eploy.net twin; that is the URL we keep.
    assert (
        job.url
        == "https://peigroupweb.eploy.net/vacancies/442/senior-reporter--private-equity.html"
    )
    assert job.location == "London, United Kingdom"
    assert "Senior Private Equity Reporter" in job.description and "Break news" in job.description
    assert "tracking" not in job.description and "Share this vacancy" not in job.description
    assert job.posted_at is not None and job.posted_at.isoformat().startswith("2026-09-14")
    assert job.extra == {"board": HOST, "id": "442"} and job.ats == "eploy"


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(eploy, "CHUNK", 1)
    handler = make_handler(load_fixture)
    assert len(search_pages(Eploy(), handler, board=HOST)) == 3
    assert len(search_pages(Eploy(), handler, board=HOST, start_page=2)) == 1


def test_bad_board_and_sitemap_index(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="not a careers host"):
        search_pages(Eploy(), lambda r: httpx.Response(200), board="acme")

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200, text="<sitemapindex><sitemap><loc>x</loc></sitemap></sitemapindex>"
        )

    with pytest.raises(ValueError, match="sitemap index"):
        search_pages(Eploy(), handler, board=HOST)


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="eploy",
        url="https://peigroupweb.eploy.net/vacancies/442/senior-reporter--private-equity.html",
        title="t",
        company="c",
    )
    assert (
        "Write exclusives" in fetch_details(Eploy(), make_handler(load_fixture), stub).description
    )


def test_url_patterns() -> None:
    assert detect("https://peigroupweb.eploy.net/vacancies/442/x.html") == (
        "eploy",
        "peigroupweb.eploy.net",
    )
    assert detect("eploy:jobs.ocs.com") == ("eploy", "jobs.ocs.com")
