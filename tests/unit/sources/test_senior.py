import json

import httpx
import pytest

from linkit_all.sources.ats.senior import Senior, work_mode
from linkit_all.sources.ats_detector import detect


def _handler(load_fixture, bodies, profile="profile"):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        body = json.loads(req.content)
        bodies.append((req.url.path.rsplit("/", 1)[-1], body))
        action = req.url.path.rsplit("/", 1)[-1]
        if action == "getProfileIdBySubdomain":
            return httpx.Response(200, json=load_fixture(f"senior/{profile}.json"))
        if action == "searchVacancies":
            return httpx.Response(200, json=load_fixture(f"senior/search{body['page']}.json"))
        return httpx.Response(200, json=load_fixture("senior/detail_v1.json"))

    return handler


def test_work_mode():
    assert work_mode(["IN_PERSON"]) == "onsite"
    assert work_mode(["hybrid", "IN_PERSON"]) == "hybrid"
    assert work_mode(["IN_PERSON", "REMOTE"]) == "remote"
    assert work_mode([]) is None and work_mode(None) is None and work_mode(["X"]) is None


def test_search_resolves_the_profile_and_pages(search_pages, load_fixture):
    bodies: list = []
    pages = search_pages(Senior(), _handler(load_fixture, bodies), board="intelbras")
    assert len(pages) == 2
    a, b = pages[0]
    (c,) = pages[1]
    assert bodies[0] == ("getProfileIdBySubdomain", {"subdomain": "intelbras"})
    search = [body for action, body in bodies if action == "searchVacancies"]
    assert [s["page"] for s in search] == [0, 1]
    assert search[0]["match"]["companies"] == [{"id": "GUID-1"}]
    assert (a.title, a.company, a.location) == (
        "Backend Engineer",
        "Intelbras",
        "Florianopolis, SC, Brasil",
    )
    assert a.url == "https://intelbras.portaldetalentos.senior.com.br/vacancy/v1"
    assert (
        a.remote == "onsite" and a.extra == {"board": "intelbras", "id": "v1"} and a.ats == "senior"
    )
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-06-10T00:00:00"
    assert (b.location, b.remote) == ("Brasil", "remote")  # the most remote model wins
    assert (c.title, c.remote) == ("Hybrid Product Manager", "hybrid")


def test_resume_and_unknown_tenant(search_pages, load_fixture):
    pages = search_pages(Senior(), _handler(load_fixture, []), board="intelbras", start_page=1)
    assert [[s.title for s in p] for p in pages] == [["Hybrid Product Manager"]]
    unknown = lambda req: httpx.Response(200, json={})  # noqa: E731
    with pytest.raises(ValueError, match="no profile id"):
        search_pages(Senior(), unknown, board="nobody")


def test_fetch_details_posts_the_vacancy_id(search_pages, fetch_details, load_fixture):
    stub = search_pages(Senior(), _handler(load_fixture, []), board="intelbras")[0][0]
    bodies: list = []
    full = fetch_details(Senior(), _handler(load_fixture, bodies), stub)
    assert full.description == "Build the backend." and full.title == stub.title
    assert bodies == [("findVacancyById", {"id": "v1"})]


def test_url_patterns():
    url = "https://intelbras.portaldetalentos.senior.com.br/vacancy/v1"
    assert detect(url) == ("senior", "intelbras")
    assert detect("senior:intelbras") == ("senior", "intelbras")
