import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.prevueaps import PrevueAPS
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def test_search_finds_the_site_id_on_the_jobs_page(search_pages, load_fixture):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/jobs/":
            return httpx.Response(200, text=load_fixture("prevueaps/jobs.html"))
        if req.url.path == "/core/jobs/889":
            assert '"showLocation": true' in req.url.params["getParams"]
            return httpx.Response(200, json=load_fixture("prevueaps/jobs.json"))
        return httpx.Response(404)

    ((a, b),) = search_pages(PrevueAPS(), handler, board="northwind")
    assert (a.title, a.company, a.location) == ("Site Supervisor", "Northwind", "Kelowna, BC")
    assert a.url == "https://northwind.prevueaps.ca/jobs/site-supervisor-31"
    assert a.description == "Full Time · Construction · 60,000 - 75,000 per year"
    assert a.extra == {"board": "northwind", "id": "31"}
    assert (b.location, b.remote, b.description) == ("Remote - Canada", "remote", "")


def test_a_page_without_a_site_id_fails_loudly(search_pages):
    def handler(req: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(404)
            if req.url.path == "/robots.txt"
            else httpx.Response(200, text="<p>")
        )

    with pytest.raises(ValueError, match="site id"):
        search_pages(PrevueAPS(), handler, board="northwind")


def test_url_patterns():
    assert detect("https://northwind.prevueaps.ca/jobs/") == ("prevueaps", "northwind")
