from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.speedrun import Speedrun
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http

HOSTED = "41dac67e-5caa-44c5-9e00-8f64b48d7c0a"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    files = {
        "/api/v1/companies/brief": "company",
        f"/api/v1/jobs/{HOSTED}": "job_hosted",
        "/api/v1/jobs/11111111-2222-3333-4444-555555555555": "job_federated",
        "/api/v1/jobs/99999999-2222-3333-4444-555555555555": "job_closed",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["source"] == "linkit"  # the API asks integrations to name themselves
        name = files.get(req.url.path)
        return (
            httpx.Response(200, json=load_fixture(f"speedrun/{name}.json"))
            if name
            else httpx.Response(404)
        )

    return handler


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Speedrun(), _serve(load_fixture), board="brief")
    assert len(pages) == 1
    hosted, federated = pages[0]  # the closed and the vanished roles are left out
    assert hosted.title == "Product Builder" and hosted.company == "Brief"
    assert hosted.url == "https://speedrun-talent-network.com/jobs/product-builder-brief-41dac67e"
    assert hosted.location == "San Francisco, CA" and hosted.remote == "onsite"
    assert hosted.description.startswith("$150K - $200K\n\nBrief is the context navigator.")
    assert hosted.posted_at is not None and hosted.posted_at.date().isoformat() == "2026-07-15"
    assert hosted.ats == "speedrun" and hosted.extra == {"board": "brief", "id": HOSTED}
    # a federated role is applied for on the company's own ATS, which the apply stage detects
    assert federated.url == federated.apply_url == "https://jobs.ashbyhq.com/brief/abc"
    assert federated.ats is None and federated.remote == "remote"


def test_resume_skips_the_first_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(Speedrun(), _serve(load_fixture), board="brief", start_page=1) == []


def test_company_error_raises(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(Speedrun(), lambda req: httpx.Response(404), board="nobody")


def test_url_patterns() -> None:
    assert detect("https://speedrun-talent-network.com/companies/brief") == ("speedrun", "brief")
    assert detect("speedrun:brief") == ("speedrun", "brief")
