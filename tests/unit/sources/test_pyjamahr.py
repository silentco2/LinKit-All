import httpx

from linkit_all.sources.ats import pyjamahr
from linkit_all.sources.ats.pyjamahr import PyjamaHR
from linkit_all.sources.ats_detector import detect


def _handler(load_fixture, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        path, page = req.url.path, req.url.params.get("page")
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/api/career/jobs/":
            return httpx.Response(200, json=load_fixture(f"pyjamahr/page{page}.json"))
        job = path.strip("/").rsplit("/", 1)[-1]
        return httpx.Response(200, json=load_fixture(f"pyjamahr/detail_{job}.json"))

    return handler


def test_search_walks_next_links_and_hydrates(search_pages, load_fixture):
    pages = search_pages(PyjamaHR(), _handler(load_fixture), board="dodo-payments")
    a, b = pages[0]
    assert (a.title, a.company, a.location) == (
        "Talent Acquisition Intern",
        "Dodo Payments",
        "Bengaluru, Karnataka, India",
    )
    assert a.url == "https://jobs.pyjamahr.com/dodo-payments/talent-acquisition-intern-2"
    assert a.description == "Great internship." and a.remote == "onsite"
    assert a.extra["id"] == "404497" and a.extra["employment"] == "INTERN"
    assert (a.salary_min, a.salary_max, a.salary_currency, a.salary_interval) == (
        15000.0,
        20000.0,
        "INR",
        "month",
    )
    assert a.posted_at is not None and a.posted_at.year == 2026
    assert b.title == "Growth Intern" and b.remote == "remote"
    assert b.salary_min is None  # salary not marked visible


def test_resume_hydrates_from_the_given_page(search_pages, load_fixture, monkeypatch):
    monkeypatch.setattr(pyjamahr, "PAGE", 1)
    pages = search_pages(PyjamaHR(), _handler(load_fixture), board="dodo-payments")
    assert [[s.title for s in p] for p in pages] == [
        ["Talent Acquisition Intern"],
        ["Growth Intern"],
    ]
    resumed = search_pages(PyjamaHR(), _handler(load_fixture), board="dodo-payments", start_page=1)
    assert [[s.title for s in p] for p in resumed] == [["Growth Intern"]]


def test_a_failed_detail_keeps_the_posting_without_a_description(search_pages, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/career/jobs/":
            return httpx.Response(200, json=load_fixture("pyjamahr/page2.json"))
        return httpx.Response(404)

    stub = search_pages(PyjamaHR(), handler, board="dodo-payments")[0][0]
    assert stub.title == "Growth Intern" and stub.description == "" and stub.remote == "remote"


def test_url_patterns():
    assert detect("https://jobs.pyjamahr.com/dodo-payments/growth-intern-sales") == (
        "pyjamahr",
        "dodo-payments",
    )
    assert detect("pyjamahr:dodo-payments") == ("pyjamahr", "dodo-payments")
