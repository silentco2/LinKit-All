from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.jibe import Jibe
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BOARD = "www.github.careers"


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/api/jobs" and req.url.params.get("page") == "1":
            return httpx.Response(200, json=load_fixture("jibe/page1.json"))
        if req.url.path == "/api/jobs" and req.url.params.get("page") == "2":
            return httpx.Response(200, json=load_fixture("jibe/page2.json"))
        return httpx.Response(200, json={"totalCount": 4, "jobs": []})

    return handler


def test_search_pages_until_the_total(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Jibe(), _serve(load_fixture), board=BOARD, calls=calls)
    assert [len(p) for p in pages] == [2, 1]  # the id-less posting is dropped
    assert len(calls) == 2 and "limit=100" in calls[0]
    gh, hybrid, remote = pages[0][0], pages[0][1], pages[1][0]
    assert gh.title == "Software Engineer III" and gh.company == "GitHub, Inc."
    assert gh.url == "https://www.github.careers/careers-home/jobs/5441" and gh.apply_url == gh.url
    assert gh.location == "US Remote" and gh.remote == "remote"  # location_type ANY: from the text
    assert gh.description == "About\nSoftware Engineer III does the work."
    assert gh.posted_at is not None and gh.posted_at.isoformat() == "2026-06-16T20:41:00"
    assert gh.extra == {"board": BOARD, "id": "5441"} and gh.ats == "jibe"
    assert hybrid.remote == "hybrid"
    assert remote.remote == "remote" and remote.company == "Github"  # no hiring_organization


def test_resume_from_the_second_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Jibe(), _serve(load_fixture), board=BOARD, start_page=1, calls=calls)
    assert [p[0].extra["id"] for p in pages] == ["5600"]
    assert len(calls) == 1 and "page=2" in calls[0]


def test_empty_board(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"totalCount": 0, "jobs": []})

    assert search_pages(Jibe(), handler, board=BOARD) == []


def test_url_patterns() -> None:
    assert detect("https://www.github.careers/careers-home/jobs/5441?lang=en") == ("jibe", BOARD)
    assert detect(f"jibe:{BOARD}") == ("jibe", BOARD)
