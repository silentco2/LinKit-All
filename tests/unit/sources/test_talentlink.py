import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.talentlink import TalentLink
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.http import Http

BOARD = "northwind.recruitmentplatform.com/FO/index.html"


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture, jobs=None):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "northwind.recruitmentplatform.com":
            if req.url.path == "/FO/index.html":
                return httpx.Response(200, text=load_fixture("talentlink/page.html"))
            return httpx.Response(404)
        assert req.url.host == "emea3.recruitmentplatform.com"
        assert req.headers["username"] == "ABCDE0123456789ABCDEFGHIJ:guest:FO"
        assert req.headers["accept"] == "application/json"
        name = {"/fo/rest/config": "config", "/fo/rest/jobs/criteria": "criteria"}.get(req.url.path)
        if name:
            return httpx.Response(200, json=load_fixture(f"talentlink/{name}.json"))
        assert req.method == "POST" and req.url.params["firstResult"] == "0"
        return httpx.Response(200, json=jobs or load_fixture("talentlink/jobs.json"))

    return handler


def test_search_reads_places_from_the_fields_the_criteria_name(search_pages, load_fixture):
    ((job,),) = search_pages(TalentLink(), _serve(load_fixture), board=BOARD)
    assert (job.title, job.company) == ("Claims Handler", "Northwind")
    assert job.location == "Leeds; United Kingdom"  # the city's bound country is added
    assert job.url == "https://northwind.recruitmentplatform.com/FO/details.html?jobId=4401"
    assert job.apply_url and "langCode=en_GB" in job.apply_url
    assert job.description == "The role\nHandle claims." and job.remote == "hybrid"
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-10-08T00:00:00"
    assert job.extra == {"board": BOARD, "id": "4401", "req": "REQ-88"}


def test_an_empty_board_and_a_page_that_is_no_widget(search_pages, load_fixture):
    empty = _serve(load_fixture, jobs={"globals": {"jobsCount": 0}})
    assert search_pages(TalentLink(), empty, board=BOARD) == []
    with pytest.raises(ValueError, match="names no TalentLink"):
        search_pages(TalentLink(), lambda req: httpx.Response(200, text="<html>"), board=BOARD)


def test_url_patterns():
    assert detect("https://northwind.recruitmentplatform.com/FO/index.html") == (
        "talentlink",
        BOARD,
    )
    assert detect("talentlink:https://jobs.acme.com/vacancies.html") == (
        "talentlink",
        "https://jobs.acme.com/vacancies.html",
    )
