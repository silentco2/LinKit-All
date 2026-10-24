import httpx
import pytest

from linkit_all.sources.ats.recruiterflow import RecruiterFlow
from linkit_all.sources.ats_detector import detect


def _serve(**pages: str):
    def handler(req: httpx.Request) -> httpx.Response:
        text = pages.get(req.url.path)
        return httpx.Response(404) if text is None else httpx.Response(200, text=text)

    return handler


def test_search_flattens_the_departments(search_pages, load_fixture):
    handler = _serve(**{"/radhires/jobs": load_fixture("recruiterflow/board.html")})
    pages = search_pages(RecruiterFlow(), handler, board="radhires")
    a, b = pages[0]
    assert (a.title, a.company, a.location) == ("Executive Assistant", "Radhires", "LATAM")
    assert a.url == "https://recruiterflow.com/radhires/jobs/431"
    assert a.remote == "remote" and a.ats == "recruiterflow"
    assert a.extra["id"] == "431" and a.extra["employment"] == "Full time"
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-09-03T19:43:26"
    assert (b.title, b.remote, b.extra["employment"]) == ("AI Engineer - LATAM", None, "Contract")


def test_empty_board_and_missing_job_list(search_pages):
    empty = '<script>window.jobsList = {"department": [], "group": []};</script>'
    assert search_pages(RecruiterFlow(), _serve(**{"/acme/jobs": empty}), board="acme") == [[]]
    with pytest.raises(ValueError, match=r"no window\.jobsList"):
        search_pages(RecruiterFlow(), _serve(**{"/acme/jobs": "<html></html>"}), board="acme")


def test_fetch_details_reads_the_json_ld(search_pages, fetch_details, load_fixture):
    stub = search_pages(
        RecruiterFlow(),
        _serve(**{"/radhires/jobs": load_fixture("recruiterflow/board.html")}),
        board="radhires",
    )[0][0]
    assert stub.description == ""
    handler = _serve(**{"/radhires/jobs/431": load_fixture("recruiterflow/job_431.html")})
    assert fetch_details(RecruiterFlow(), handler, stub).description == "Support the team."
    assert fetch_details(RecruiterFlow(), _serve(**{"/radhires/jobs/431": "<html/>"}), stub) == stub


def test_url_patterns():
    assert detect("https://recruiterflow.com/radhires/jobs") == ("recruiterflow", "radhires")
    assert detect("https://recruiterflow.com/radhires/jobs/431") == ("recruiterflow", "radhires")
    assert detect("recruiterflow:radhires") == ("recruiterflow", "radhires")
