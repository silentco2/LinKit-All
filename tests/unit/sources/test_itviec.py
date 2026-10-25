from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.base import JobStub
from linkit_all.sources.boards.itviec import ITviec, description_html, parse_cards
from linkit_all.sources.http import Http

MB = "https://itviec.com/it-jobs/data-quality-management-specialist-data-division-mb-bank-5856"
BASE = "https://itviec.com/it-jobs/"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/it-jobs":
            name = "list_past_end" if req.url.params.get("page") else "list_page1"
            return httpx.Response(200, text=load_fixture(f"itviec/{name}.html"))
        if path.endswith("-5856"):
            return httpx.Response(200, text=load_fixture("itviec/detail_salary.html"))
        if path.endswith("-5536"):
            return httpx.Response(200, text=load_fixture("itviec/detail_hidden_salary.html"))
        return httpx.Response(404)

    return handler


def test_parse_cards(load_fixture: Callable[[str], Any]) -> None:
    cards = parse_cards(load_fixture("itviec/list_page1.html"))
    assert len(cards) == 4 and cards[1] == ("4bf8bdb8-e735-4205-a17e-891be1e1ffbd", MB)
    # the "company spotlight" links on the past-the-end page carry no card key
    assert parse_cards(load_fixture("itviec/list_past_end.html")) == []


def test_search(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(ITviec(), _serve(load_fixture))
    assert len(pages) == 1  # page 2 adds nothing: the end
    by_url = {s.url: s for s in pages[0]}
    assert set(by_url) == {MB, BASE + "senior-data-security-data-division-mb-bank-5536"}  # 2 gone
    job = by_url[MB]
    assert job.title == "AI Software Engineer (Python/Go/C/C++ & AI Agents)"
    assert job.company == "MB Bank"
    assert job.location == "Hà Nội, Vietnam"
    assert job.remote == "onsite"
    assert "Top 3 Reasons To Join Us" in job.description and "<" not in job.description
    assert job.posted_at is not None and job.posted_at.date().isoformat() == "2026-09-24"
    assert (job.salary_min, job.salary_max, job.salary_currency) == (800, 2000, "USD")
    assert job.salary_interval == "month"
    assert job.extra["id"] == "4bf8bdb8-e735-4205-a17e-891be1e1ffbd" and job.ats == "itviec"
    assert "Python" in job.extra["skills"]


def test_hidden_salary_is_not_a_salary(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    stubs = [s for p in search_pages(ITviec(), _serve(load_fixture)) for s in p]
    hidden = next(s for s in stubs if s.url.endswith("-5536"))
    assert hidden.company == "ITviec Recruitment Consulting"
    assert hidden.salary_min is None and hidden.salary_currency is None
    assert hidden.location == "Hồ Chí Minh, Vietnam"  # "Not Available" locality is ignored


def test_limit_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert [len(p) for p in search_pages(ITviec(), _serve(load_fixture), limit=1)] == [1]
    assert search_pages(ITviec(), _serve(load_fixture), start_page=1) == []


def test_description_html() -> None:
    html = description_html("The Job\r\nplain line\n<p>markup</p>\n\n")
    assert html == "<h3>The Job</h3><p>plain line</p><p>markup</p>"
