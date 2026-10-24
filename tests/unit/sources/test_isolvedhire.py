from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.isolvedhire import ApplicantPro, IsolvedHire
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Source
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(
    load_fixture: Callable[[str], Any], sitemap: str | None = None, domain: str = "isolvedhire.com"
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/sitemap.xml":
            xml = sitemap or load_fixture("isolvedhire/sitemap.xml").replace(
                "isolvedhire.com", domain
            )
            return httpx.Response(200, text=xml)
        if req.url.path == "/jobs/1792515":
            return httpx.Response(200, text=load_fixture("isolvedhire/detail.html"))
        return httpx.Response(404)

    return handler


@pytest.mark.parametrize(
    ("source", "domain"), [(IsolvedHire(), "isolvedhire.com"), (ApplicantPro(), "applicantpro.com")]
)
def test_both_domains(
    source: Source,
    domain: str,
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
) -> None:
    pages = search_pages(source, _serve(load_fixture, domain=domain), board="acme")
    jobs = [j for p in pages for j in p]
    assert len(jobs) == 1  # /jobs/<id> and /jobs/<id>.html are one posting; other pages are no job
    job = jobs[0]
    assert job.title == "Post-Harvest Technician" and job.company == "Crisp Community LLC"
    assert job.url == f"https://acme.{domain}/jobs/1792515"
    assert job.location == "Norwich, CT, US"
    assert job.description == "Trim plants."
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-06-11T00:00:00"
    assert job.extra == {
        "employment": None,
        "valid_through": None,
        "board": "acme",
        "id": "1792515",
    }
    assert job.ats == source.name


def test_resume_past_the_end(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(IsolvedHire(), _serve(load_fixture), board="acme", start_page=1) == []


def test_a_board_the_platform_no_longer_serves(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = _serve(load_fixture, sitemap=load_fixture("isolvedhire/gone.html"))
    with pytest.raises(Unsupported, match="not served"):
        search_pages(IsolvedHire(), handler, board="acme")


def test_url_patterns() -> None:
    assert detect("https://acme.isolvedhire.com/jobs/1792515") == ("isolvedhire", "acme")
    assert detect("https://acme.applicantpro.com/jobs/") == ("applicantpro", "acme")
    assert detect("applicantpro:acme") == ("applicantpro", "acme")
    assert detect("https://www.isolvedhire.com/") is None
