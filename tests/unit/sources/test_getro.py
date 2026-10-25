import json

import httpx
import pytest

from linkit_all.sources import registry
from linkit_all.sources.ats import getro
from linkit_all.sources.ats.getro import Getro
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

API_PATH = "/api/v2/collections/15272/search/jobs"


def _handler(load_fixture, bodies=None, per_page=100):
    rows = load_fixture("getro/search.json")["results"]["jobs"]

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "jobsinvc.getro.com":
            return httpx.Response(200, text=load_fixture("getro/home.html"))
        assert req.url.path == API_PATH
        body = json.loads(req.content)
        if bodies is not None:
            bodies.append(body)
        page = body["page"]
        chunk = rows[page * per_page : (page + 1) * per_page]
        return httpx.Response(200, json={"results": {"count": len(rows), "jobs": chunk}})

    return handler


def test_search_resolves_the_network_id_and_maps_postings(search_pages, load_fixture):
    bodies: list[dict] = []
    pages = search_pages(Getro(), _handler(load_fixture, bodies), board="jobsinvc")
    assert bodies == [{"hits_per_page": 100, "page": 0}] and [len(p) for p in pages] == [2]
    acme, beta = pages[0]  # the company-less posting is dropped
    assert (acme.title, acme.company, acme.location) == (
        "Desktop Analyst", "Acme", "Zürich, Switzerland",
    )  # fmt: skip
    assert acme.url == "https://jobsinvc.getro.com/companies/acme-1/jobs/101-desktop-analyst"
    assert acme.apply_url == "https://boards.greenhouse.io/acme/jobs/1"
    assert acme.remote == "onsite" and acme.ats == "getro" and acme.extra["id"] == 101
    assert acme.posted_at is not None and acme.posted_at.year == 2023
    assert beta.remote == "remote"


def test_search_pages_until_the_count_and_resumes(search_pages, load_fixture, monkeypatch):
    monkeypatch.setattr(getro, "PAGE", 2)
    bodies: list[dict] = []
    pages = search_pages(Getro(), _handler(load_fixture, bodies, per_page=2), board="jobsinvc")
    assert [b["page"] for b in bodies] == [0, 1] and [len(p) for p in pages] == [2]
    resumed = search_pages(
        Getro(), _handler(load_fixture, per_page=2), board="jobsinvc", start_page=1
    )
    assert resumed == []  # page 1 holds only the dropped posting


def test_search_fails_by_name_when_the_board_has_no_network_id(search_pages):
    handler = lambda req: httpx.Response(200, text="<html></html>")  # noqa: E731
    with pytest.raises(ValueError, match="no network id"):
        search_pages(Getro(), handler, board="jobsinvc")


def test_fetch_details_reads_the_description_from_the_page(fetch_details, load_fixture):
    handler = lambda req: httpx.Response(200, text=load_fixture("getro/detail.html"))  # noqa: E731
    stub = JobStub(
        source="getro",
        url="https://jobsinvc.getro.com/companies/acme-1/jobs/101-desktop-analyst",
        title="t", company="c",
    )  # fmt: skip
    assert fetch_details(Getro(), handler, stub).description == "Great role"


def test_url_patterns_route_boards_and_ignore_getro_s_own_hosts():
    assert detect("https://jobsinvc.getro.com/jobs") == ("getro", "jobsinvc")
    assert detect("getro:jobsinvc") == ("getro", "jobsinvc")
    assert detect("https://api.getro.com/api/v2/collections/1") != ("getro", "api")
    assert detect("https://www.getro.com/pricing") != ("getro", "www")
    assert registry()["getro"].kind == "ats"
