import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.dayforce import PAGE_SIZE, Dayforce
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_search_bootstraps_csrf_and_maps_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    data = load_fixture("dayforce/search_page.json")
    sent: list[tuple[str, dict[str, Any]]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            assert req.url.path == "/api/auth/csrf"
            return httpx.Response(200, json={"csrfToken": "tok"})
        sent.append((req.headers["X-CSRF-TOKEN"], json.loads(req.content)))
        return httpx.Response(200, json=data)

    pages = search_pages(Dayforce(), handler, board="dcrusa/join-us")
    assert sent == [
        (
            "tok",
            {
                "clientNamespace": "dcrusa",
                "jobBoardCode": "join-us",
                "cultureCode": "en-US",
                "paginationStart": 0,
            },
        )
    ]
    assert len(pages) == 1
    sited, virtual = pages[0]
    assert sited.title == "Backend Engineer" and sited.company == "Dcrusa"
    assert sited.url == "https://jobs.dayforcehcm.com/en-US/dcrusa/join-us/jobs/2566"
    assert sited.location == "Houston, TX, US; Toronto, ON, CA"  # repeated place listed once
    assert sited.description.startswith("We\u2019re hiring.\n\nYou will:\n- ship Go")
    assert sited.posted_at is not None and sited.posted_at.year == 2026
    assert sited.extra == {"board": "dcrusa/join-us", "id": 2566} and sited.ats == "dayforce"
    assert virtual.remote == "remote" and virtual.location == ""


def test_culture_paging_and_stale_token(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    def posting(i: int) -> dict[str, Any]:
        return {"jobPostingId": i, "jobTitle": f"role {i}", "jobDescription": "body"}

    tokens = iter(["old", "new"])
    offsets: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "GET":
            return httpx.Response(200, json={"csrfToken": next(tokens, "new")})
        if req.headers["X-CSRF-TOKEN"] == "old":
            return httpx.Response(403)  # a stale token looks like a 403
        body = json.loads(req.content)
        assert body["cultureCode"] == "fr-CA"
        offsets.append(body["paginationStart"])
        start = body["paginationStart"]
        count = PAGE_SIZE if start == 0 else 1
        items = [posting(start + n + 1) for n in range(count)]
        return httpx.Response(200, json={"maxCount": PAGE_SIZE + 1, "jobPostings": items})

    pages = search_pages(Dayforce(), handler, board="gm/candidateportal/fr-CA")
    assert [len(p) for p in pages] == [PAGE_SIZE, 1] and offsets == [0, PAGE_SIZE]
    assert pages[1][0].url == "https://jobs.dayforcehcm.com/fr-CA/gm/candidateportal/jobs/26"
    resumed = search_pages(Dayforce(), handler, board="gm/candidateportal/fr-CA", start_page=1)
    assert [len(p) for p in resumed] == [1]


def test_errors(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="tenant/site"):
        search_pages(Dayforce(), lambda req: httpx.Response(200, json={}), board="dcrusa")
    with pytest.raises(ValueError, match="no token"):
        search_pages(Dayforce(), lambda req: httpx.Response(200, json={}), board="a/b")


def test_url_patterns() -> None:
    for url in (
        "https://jobs.dayforcehcm.com/en-US/dcrusa/join-us",
        "https://jobs.dayforcehcm.com/dcrusa/join-us/jobs/12",
    ):
        assert detect(url) == ("dayforce", "dcrusa/join-us")
    assert detect("dayforce:gm/candidateportal/fr-CA") == ("dayforce", "gm/candidateportal/fr-CA")
