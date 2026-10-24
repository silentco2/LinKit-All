from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.itechart import ITechArt
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text=load_fixture("itechart/sitemap.xml"))
        if req.url.path == "/job-openings/ai-solution-architect-minsk":
            return httpx.Response(200, text=load_fixture("itechart/detail.html"))
        return httpx.Response(404)

    return handler


def test_it_is_a_company_plugin_run_on_request() -> None:
    source = registry()["itechart"]
    assert source.kind == "company"
    cfg = SearchConfig()
    assert not source.is_enabled(cfg)
    task = source.tasks(cfg)[0]
    assert task.board == "itechartgroup.by"


def test_search_lists_the_vacancies_from_the_sitemap(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(ITechArt(), _serve(load_fixture), board="itechartgroup.by")
    jobs = [j for p in pages for j in p]
    assert len(jobs) == 1  # the /job-openings listing and /about are not vacancies
    job = jobs[0]
    assert job.title == "AI Solution Architect" and job.company == "iTechArt"
    assert job.url == "https://itechartgroup.by/job-openings/ai-solution-architect-minsk"
    assert job.location == "Минск" and job.description == "build"
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-06-14T07:54:08"
    assert job.extra["id"] == "ai-solution-architect-minsk" and job.ats == "itechart"
    assert (
        search_pages(ITechArt(), _serve(load_fixture), board="itechartgroup.by", start_page=1) == []
    )
