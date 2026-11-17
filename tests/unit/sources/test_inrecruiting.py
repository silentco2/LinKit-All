from urllib.parse import parse_qs

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats.inrecruiting import InRecruiting
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch):
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(load_fixture, forms):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/it/career":
            return httpx.Response(200, text=load_fixture("inrecruiting/career.html"))
        if req.url.path == "/app.php" and req.method == "POST":
            assert req.url.host == "northwind.intervieweb.it"
            assert req.url.params["CSRFToken"] == "tok" and req.url.params["IdAzienda"] == "77"
            forms.append(parse_qs(req.content.decode(), keep_blank_values=True))
            return httpx.Response(200, json=load_fixture("inrecruiting/page2.json"))
        return httpx.Response(404)

    return handler


def test_search_follows_the_pages_own_next_request(search_pages, load_fixture):
    forms: list[dict] = []
    first, second = search_pages(InRecruiting(), _serve(load_fixture, forms), board="northwind")
    a, b = first
    assert (a.title, a.company, a.location) == ("Sviluppatore Java", "Northwind", "Bologna (BO)")
    assert a.url == "https://northwind.intervieweb.it/jobs/sviluppatore-java-1001/it/"
    assert a.extra == {"board": "northwind", "id": "1001"}
    assert b.remote == "remote"
    assert [s.title for s in second] == ["Magazziniere"] and second[0].location == "Parma"
    assert forms[0]["act1"] == ["vacancyListCareer"] and forms[0]["section"] == ["abc_123"]
    assert forms[0]["page"] == ["2"] and forms[0]["order"] == ["date_desc"]


def test_resume_skips_the_first_page(search_pages, load_fixture):
    pages = search_pages(InRecruiting(), _serve(load_fixture, []), board="northwind", start_page=1)
    assert [[s.title for s in p] for p in pages] == [["Magazziniere"]]


def test_url_patterns():
    assert detect("https://northwind.intervieweb.it/it/career") == ("inrecruiting", "northwind")
    assert detect("https://inrecruiting.intervieweb.it/") is None
