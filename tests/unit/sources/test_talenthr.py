from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.talenthr import TalentHR
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/dnext":
            return httpx.Response(200, text=load_fixture("talenthr/listing.html"))
        if req.url.path == "/dnext/senior-backend-developer-2/22":
            return httpx.Response(200, text=load_fixture("talenthr/detail.html"))
        return httpx.Response(404)  # robots.txt, and /dnext/gone/12

    return handler


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(TalentHR(), _serve(load_fixture), board="dnext")
    assert len(pages) == 1 and len(pages[0]) == 1  # no slug: cannot be addressed; gone: skipped
    job = pages[0][0]
    assert job.title == "Senior Backend Developer" and job.company == "Dnext"
    assert job.url == "https://jobs.talenthr.io/dnext/senior-backend-developer-2/22"
    assert job.location == "CH" and job.remote == "remote"  # employment_type is the work mode
    assert "Own the backend." in job.description and "alert" not in job.description
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-07-17T10:33:19"
    assert job.extra == {"board": "dnext", "id": "22"} and job.ats == "talenthr"


def test_a_board_page_without_job_data_is_refused(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    with pytest.raises(Unsupported):
        search_pages(
            TalentHR(), lambda req: httpx.Response(200, text="<html></html>"), board="dnext"
        )


def test_url_patterns() -> None:
    assert detect("https://jobs.talenthr.io/dnext/senior-backend-developer-2/22") == (
        "talenthr",
        "dnext",
    )
    assert detect("talenthr:dnext") == ("talenthr", "dnext")
