from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.ukgready import UKGReady, split_board
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def handler_for(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path.endswith("/job-requisitions"):
            return httpx.Response(200, json=load_fixture("ukgready/listing.json"))
        if path.endswith("/job-requisitions/1040452356"):
            return httpx.Response(200, json=load_fixture("ukgready/detail.json"))
        if path.endswith("/format-settings"):
            return httpx.Response(200, json=load_fixture("ukgready/settings.json"))
        return httpx.Response(404)

    return handler


def test_lists_then_hydrates_each_posting(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        UKGReady(), handler_for(load_fixture), board="Secure4.saashr.com/6162397", calls=calls
    )
    assert calls[0] == (
        "https://secure4.saashr.com/ta/rest/ui/recruitment/companies/%7C6162397"
        "/job-requisitions?offset=1&size=200"
    )
    assert len(pages) == 1 and len(pages[0]) == 1  # the second posting's detail 404s: skipped
    job = pages[0][0]
    assert job.title == "Backend Engineer" and job.company == "6162397"
    assert job.url == "https://secure4.saashr.com/ta/6162397.careers?ShowJob=1040452356"
    assert job.location == "Merrillville, IN, USA" and job.remote is None
    assert "Full body" in job.description and "Five years" in job.description
    assert "truncated preview" not in job.description and "x()" not in job.description
    assert (job.salary_min, job.salary_max) == (32.5, 41)
    assert job.salary_currency == "USD" and job.salary_interval == "hour"
    assert job.extra == {
        "board": "secure4.saashr.com/6162397",
        "id": "1040452356",
        "employment": "FT Non-Exempt",
    }


def test_pay_without_a_currency_is_dropped_and_remote_flag(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    base = handler_for(load_fixture)

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/format-settings"):
            return httpx.Response(404)
        if req.url.path.endswith("/1040451353"):
            return httpx.Response(200, json={"job_description": "<p>Numbers</p>"})
        return base(req)

    pages = search_pages(UKGReady(), handler, board="secure4.saashr.com/6162397")
    backend, analyst = pages[0]
    assert backend.salary_min is None and backend.salary_currency is None
    assert analyst.remote == "remote" and analyst.location == "Sydney, AUS"
    assert analyst.salary_min is None  # no amounts, though a period is stated


def test_pages_by_number_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("linkit_all.sources.ats.ukgready.CHUNK", 1)
    listed: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/job-requisitions"):
            page = int(req.url.params["offset"])
            listed.append(page)
            rows = [{"id": page * 10 + i, "job_title": "T", "location": {}} for i in (1, 2)]
            return httpx.Response(200, json={"_paging": {"total": 4}, "job_requisitions": rows})
        return httpx.Response(200, json={"job_description": "d"})

    pages = search_pages(UKGReady(), handler, board="h.saashr.com/1")
    assert listed == [1, 2] and [len(p) for p in pages] == [1, 1, 1, 1]
    resumed = search_pages(UKGReady(), handler, board="h.saashr.com/1", start_page=3)
    assert [len(p) for p in resumed] == [1] and resumed[0][0].extra["id"] == "22"


def test_bad_board_and_url_patterns() -> None:
    with pytest.raises(ValueError, match="host>/<tenant"):
        split_board("6162397")
    with pytest.raises(ValueError, match="host>/<tenant"):
        split_board("secure4.saashr.com/6162397/extra")
    assert detect("https://secure4.saashr.com/ta/6162397.careers?ShowJob=1040452356") == (
        "ukgready",
        "secure4.saashr.com/6162397",
    )
    assert detect("https://aus-secure.prd.mykronos.com/ta/6183838.careers") == (
        "ukgready",
        "aus-secure.prd.mykronos.com/6183838",
    )
    assert detect("https://secure.workforceready.com.au/ta/6179255.careers") == (
        "ukgready",
        "secure.workforceready.com.au/6179255",
    )
