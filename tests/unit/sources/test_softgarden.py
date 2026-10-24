from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.softgarden import Softgarden
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http

URL = (
    "https://bundesdruckerei.softgarden.io/job/66221618/creative-producer?jobDbPVId=279489843&l=en"
)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/":
            return httpx.Response(200, text=load_fixture("softgarden/listing.html"))
        if req.url.path == "/job/66221618/creative-producer":
            return httpx.Response(200, text=load_fixture("softgarden/detail.html"))
        return httpx.Response(404)  # robots.txt, and the second listed job is gone

    return handler


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Softgarden(), _serve(load_fixture), board="bundesdruckerei")
    assert (
        len(pages) == 1 and len(pages[0]) == 1
    )  # the repeated link counts once, the gone one drops
    job = pages[0][0]
    assert job.title == "Creative Producer" and job.company == "Bundesdruckerei"
    assert job.url == URL and job.apply_url == URL and job.ats == "softgarden"
    assert job.location == "Berlin, Deutschland"
    assert "Build" in job.description and "alert" not in job.description
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-07-21T10:43:08.524000"
    assert job.extra["board"] == "bundesdruckerei" and job.extra["id"] == "66221618"


def test_url_patterns() -> None:
    assert detect(URL) == ("softgarden", "bundesdruckerei")
    assert detect("softgarden:bundesdruckerei") == ("softgarden", "bundesdruckerei")
