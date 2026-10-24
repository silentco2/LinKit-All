from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.talentlyft import TalentLyft
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text=load_fixture("talentlyft/sitemap.xml"))
        if req.url.path == "/jobs/senior-electronics-engineer-cjVz":
            return httpx.Response(200, text=load_fixture("talentlyft/detail.html"))
        return httpx.Response(404)

    return handler


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(TalentLyft(), _serve(load_fixture), board="inetec")
    assert len(pages) == 1 and len(pages[0]) == 1  # the root has no code, the other posting is gone
    job = pages[0][0]
    assert job.title == "Senior Electronics Engineer" and job.company == "INETEC"
    assert job.url == "https://inetec.talentlyft.com/jobs/senior-electronics-engineer-cjVz"
    assert job.location == "Donji Stupnik, Croatia"
    assert "eddy current" in job.description and "alert" not in job.description
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-06-23"
    assert job.extra["board"] == "inetec" and job.extra["id"] == "cjVz" and job.ats == "talentlyft"


def test_url_patterns() -> None:
    assert detect("https://inetec.talentlyft.com/jobs/senior-electronics-engineer-cjVz") == (
        "talentlyft",
        "inetec",
    )
    assert detect("talentlyft:inetec") == ("talentlyft", "inetec")
