import copy
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import cornerstone
from linkit_all.sources.ats.cornerstone import Cornerstone
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

EMPTY = {"status": "200", "data": {"totalCount": 0, "requisitions": []}}


def _handler(home: str, by_site: dict[int, Any], bodies: list[dict[str, Any]]) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.method == "GET":
            return httpx.Response(200, text=home)
        assert req.headers["Authorization"] == "Bearer eyJhbGciTESTtoken123"
        body = json.loads(req.content)
        bodies.append(body)
        return httpx.Response(200, json=by_site.get(body["careerSiteId"], EMPTY))

    return handler


def test_search_scrapes_token_then_maps_requisitions(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cornerstone, "MAX_SITES", 3)  # requests are rate limited even in tests
    bodies: list[dict[str, Any]] = []
    jobs = load_fixture("cornerstone/jobs.json")
    handler = _handler(load_fixture("cornerstone/home.html"), {1: jobs}, bodies)
    pages = search_pages(Cornerstone(), handler, board="nintendoeurope")
    assert len(pages) == 1 and len(pages[0]) == 1
    j = pages[0][0]
    assert j.title == "European Operations Administrator" and j.company == "Nintendoeurope"
    assert j.location == "Frankfurt am Main, DE"
    assert j.url == (
        "https://nintendoeurope.csod.com/ux/ats/careersite/1/home/requisition/494?c=nintendoeurope"
    )
    assert "Coordinate shipments." in j.description and "alert" not in j.description
    assert j.posted_at is not None and (j.posted_at.month, j.posted_at.day) == (6, 15)
    assert j.extra == {"board": "nintendoeurope", "id": 494, "site": 1}
    assert {b["careerSiteId"] for b in bodies} == {1, 2, 3}  # every site id is probed


def test_later_site_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cornerstone, "MAX_SITES", 4)
    jobs = load_fixture("cornerstone/jobs.json")
    other = copy.deepcopy(jobs)
    other["data"]["requisitions"][0].update(requisitionId=900, displayJobTitle="Second site")
    handler = _handler(load_fixture("cornerstone/home.html"), {1: jobs, 3: other, 4: jobs}, [])
    pages = search_pages(Cornerstone(), handler, board="krka")
    assert [p[0].extra["site"] for p in pages] == [1, 3]  # site 4 repeats id 494: not listed twice
    resumed = search_pages(Cornerstone(), handler, board="krka", start_page=1)
    assert [p[0].title for p in resumed] == ["Second site"]


def test_page_without_token(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    handler = _handler("<html></html>", {}, [])
    with pytest.raises(ValueError, match="no API endpoint"):
        search_pages(Cornerstone(), handler, board="x")


def test_url_patterns() -> None:
    url = "https://nintendoeurope.csod.com/ux/ats/careersite/1/home?c=x"
    assert detect(url) == ("cornerstone", "nintendoeurope")
    assert detect("cornerstone:krka") == ("cornerstone", "krka")
