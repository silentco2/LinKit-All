from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.freshteam import Freshteam, job_links
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/jobs":
            page = req.url.params["page"]
            return httpx.Response(200, text=load_fixture(f"freshteam/listing_{page}.html"))
        if path.startswith("/jobs/8OA37qwQgD2C"):
            return httpx.Response(200, text=load_fixture("freshteam/job_remote.html"))
        return httpx.Response(200, text=load_fixture("freshteam/job_onsite.html"))

    return handler


def test_listing_pages_then_details(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Freshteam(), make_handler(load_fixture), board="simera-talent")
    assert len(pages) == 1 and len(pages[0]) == 2  # the duplicate Apply link is merged
    a, b = pages[0]
    assert a.title == "Back End Developer" and a.company == "Simera"
    assert a.url == "https://simera-talent.freshteam.com/jobs/8OA37qwQgD2C/back-end-developer-br-3"
    assert a.location == "San Francisco, United States of America" and a.remote == "remote"
    assert "Build" in a.description and "& ship." in a.description  # entity-encoded markup
    assert "alert" not in a.description and "<" not in a.description
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-06-17T20:44:40"
    assert a.extra == {
        "employment": "FULL_TIME",
        "valid_through": None,
        "board": "simera-talent",
        "id": "8OA37qwQgD2C",
    }
    assert b.remote is None and b.extra["id"] == "_-MH_W5oSn7f"


def test_resume_and_job_links(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(Freshteam(), make_handler(load_fixture), board="x", start_page=1) == []
    links = job_links(load_fixture("freshteam/listing_1.html"), "https://x.freshteam.com/jobs")
    assert links == [
        "https://x.freshteam.com/jobs/8OA37qwQgD2C/back-end-developer-br-3",
        "https://simera-talent.freshteam.com/jobs/_-MH_W5oSn7f/seo-manager-bolivia",
    ]


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    url = "https://x.freshteam.com/jobs/_-MH_W5oSn7f/seo-manager-bolivia"
    stub = JobStub(source="freshteam", url=url, title="t", company="c")
    assert (
        fetch_details(Freshteam(), make_handler(load_fixture), stub).description == "Grow traffic."
    )


def test_gone_job_is_dropped(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    base = make_handler(load_fixture)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(410) if "_-MH_W5oSn7f" in req.url.path else base(req)

    pages = search_pages(Freshteam(), handler, board="simera-talent")
    assert [j.title for j in pages[0]] == ["Back End Developer"]


def test_url_patterns() -> None:
    assert detect("https://simera-talent.freshteam.com/jobs") == ("freshteam", "simera-talent")
    assert detect("freshteam:simera-talent") == ("freshteam", "simera-talent")
    assert detect("https://www.freshteam.com/") is None


@pytest.mark.parametrize("href", ["/jobs", "/jobs/search", "/about"])
def test_non_job_links_are_ignored(href: str) -> None:
    assert job_links(f'<a href="{href}">x</a>', "https://x.freshteam.com/jobs") == []
