from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.base import JobStub
from linkit_all.sources.boards.instaffo import Instaffo
from linkit_all.sources.http import Http

DE = "https://jobs.instaffo.com/de/job/junior-it-consultant-m-f-d-5b3d78bc1bd5"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text=load_fixture("instaffo/sitemap.xml"))
        if req.url.path == "/sitemap-jobs.xml":
            return httpx.Response(200, text=load_fixture("instaffo/sitemap-jobs.xml"))
        if req.url.path == "/de/job/junior-it-consultant-m-f-d-5b3d78bc1bd5":
            return httpx.Response(200, text=load_fixture("instaffo/detail.html"))
        return httpx.Response(404)

    return handler


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Instaffo(), _serve(load_fixture), query="x", calls=calls)
    stubs = [s for p in pages for s in p]
    # the /en twin and the non-job page are never fetched; the /de posting that is gone is dropped
    assert [s.url for s in stubs] == [DE]
    assert not any("/en/job/" in c or "/talent/" in c for c in calls)
    job = stubs[0]
    assert job.title == "Junior IT Consultant (m/f/d)"
    assert job.company == "UCG United Consulting Group GmbH"
    assert job.location == "Frankfurt am Main, DE"
    assert job.description.startswith("Junior IT Consultant (m/f/d)")
    assert "<" not in job.description
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-08-26"
    assert job.extra["id"] == "junior-it-consultant-m-f-d-5b3d78bc1bd5"
    assert job.ats == "instaffo" and job.apply_url == DE


def test_old_or_undated_postings_are_dropped(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    old = load_fixture("instaffo/detail.html").replace("2026-08-26", "2020-01-01")
    base = _serve(load_fixture)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/de/job/junior"):
            return httpx.Response(200, text=old)
        return base(req)

    assert [s for p in search_pages(Instaffo(), handler) for s in p] == []


def test_tasks_and_limit(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    from linkit_all.core.search import SearchConfig

    cfg = SearchConfig.model_validate({"search": {"queries": ["a", "b"]}})
    tasks = Instaffo().tasks(cfg)
    assert len(tasks) == 1 and tasks[0].limit == 400  # one feed stands in for both queries
    calls: list[str] = []
    search_pages(Instaffo(), _serve(load_fixture), limit=0, calls=calls)
    assert not any("/de/job/" in c for c in calls)
