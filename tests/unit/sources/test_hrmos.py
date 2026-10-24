from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.hrmos import Hrmos, job_links
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(routes: dict[str, str]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        for key in sorted(routes, key=len, reverse=True):
            if key in str(req.url):
                return httpx.Response(200, text=routes[key])
        return httpx.Response(404)

    return handler


def _routes(load_fixture: Callable[[str], Any]) -> dict[str, str]:
    return {
        "page=1": load_fixture("hrmos/page1.html"),
        "page=2": load_fixture("hrmos/page2.html"),
        "page=3": load_fixture("hrmos/page3.html"),
        "/jobs/job1": load_fixture("hrmos/job1.html"),
        "/jobs/job2": load_fixture("hrmos/job2.html"),
    }


def test_search_pages_until_empty(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Hrmos(), _serve(_routes(load_fixture)), board="acme")
    assert [len(p) for p in pages] == [1, 1]
    one, two = pages[0][0], pages[1][0]
    assert one.title == "Backend Engineer" and one.location == "Shibuya, Tokyo"
    assert one.url == "https://hrmos.co/pages/acme/jobs/job1" and one.apply_url == one.url
    assert one.company == "Acme" and one.ats == "hrmos" and one.description == "Build things."
    assert one.posted_at is not None and one.posted_at.year == 2025
    assert one.extra["board"] == "acme" and one.extra["id"] == "job1"
    assert one.extra["employment"] == "FULL_TIME" and two.extra["employment"] == "CONTRACTOR"


def test_resume_skips_earlier_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Hrmos(), _serve(_routes(load_fixture)), board="acme", start_page=1, calls=calls
    )
    assert [p[0].title for p in pages] == ["Frontend Engineer"]
    assert not any("page=1" in c for c in calls)


def test_job_links_keep_only_this_boards_jobs(load_fixture: Callable[[str], Any]) -> None:
    html = load_fixture("hrmos/page1.html")
    assert job_links(html, "acme") == ["https://hrmos.co/pages/acme/jobs/job1"]
    assert job_links(html, "other") == []  # the bare listing, board root, deeper and foreign links


def test_url_patterns() -> None:
    assert detect("https://hrmos.co/pages/cyberagent-group/jobs") == ("hrmos", "cyberagent-group")
    assert detect("https://hrmos.co/pages/1218800560317673472/jobs/001") == (
        "hrmos",
        "1218800560317673472",
    )
    assert detect("hrmos:acme") == ("hrmos", "acme")
