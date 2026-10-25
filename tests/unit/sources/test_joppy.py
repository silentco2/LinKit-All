from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.base import JobStub
from linkit_all.sources.boards.joppy import Joppy, company_slugs, work_mode
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/sitemap.directory.xml":
            return httpx.Response(200, text=load_fixture("joppy/sitemap.xml"))
        if req.url.path == "/companies/seidor":
            return httpx.Response(200, text=load_fixture("joppy/company.html"))
        return httpx.Response(404)  # empty-co has no page

    return handler


def test_company_slugs(load_fixture: Callable[[str], Any]) -> None:
    assert company_slugs(load_fixture("joppy/sitemap.xml")) == ["empty-co", "seidor"]


def test_work_mode() -> None:
    assert work_mode({"isHybrid": True, "isRemote": True}) == "hybrid"
    assert work_mode({"isRemote": True}) == "remote"
    assert work_mode({"isOffice": True}) == "onsite"
    assert work_mode({"isRemote": True, "isOffice": True}) is None


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Joppy(), _serve(load_fixture))
    assert len(pages) == 1
    stubs = pages[0]
    assert len(stubs) == 2  # the job without an id is dropped
    job = next(s for s in stubs if s.title.startswith("Consultor/a SAP Log"))
    assert job.company == "SEIDOR"
    assert job.url == "https://www.joppy.me/companies/seidor/14d16b99-0cdb-4813-8644-dd6f3ccf0d64"
    assert job.extra["id"] == "14d16b99-0cdb-4813-8644-dd6f3ccf0d64" and job.ats == "joppy"
    assert job.apply_url == job.url and job.location
    assert "Must-have skills: SAP SD, Sap Mm, SAP." in job.description
    assert job.remote == "hybrid" and job.location.startswith("Seville, Spain; Madrid")
    assert "<" not in job.description
    assert (job.salary_min is None) == (job.salary_currency is None)


def test_salary_only_when_public() -> None:
    joppy = Joppy()
    job: dict[str, Any] = {
        "uid": "u1",
        "title": "Dev",
        "description": "<p>x</p>",
        "place": {"isRemote": True},
        "salaryMin": 40000,
        "salaryMax": 50000,
        "isSalaryPublic": True,
        "languages": [{"name": "spanish", "level": 5}],
        "sponsorVisa": True,
    }
    pay = joppy.stub(job, "Acme", "acme")
    assert pay is not None
    assert (pay.salary_min, pay.salary_max, pay.salary_currency) == (40000, 50000, "EUR")
    assert pay.salary_interval == "year" and pay.remote == "remote"
    assert "spanish (level 5/5)" in pay.description and "sponsors a work visa" in pay.description
    hidden = joppy.stub({**job, "isSalaryPublic": False}, "Acme", "acme")
    assert hidden is not None and hidden.salary_min is None
    assert joppy.stub({**job, "uid": ""}, "Acme", "acme") is None


def test_limit_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert [len(p) for p in search_pages(Joppy(), _serve(load_fixture), limit=1)] == [1]
    assert search_pages(Joppy(), _serve(load_fixture), start_page=1) == []
