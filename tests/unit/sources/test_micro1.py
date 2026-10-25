from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import micro1
from linkit_all.sources.companies.micro1 import Micro1, parse_post

POST = "https://jobs.micro1.ai/post/dcb37b06-8e05-434d-ac22-372a4c04cefc"


def site(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handle(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text=load_fixture("micro1/sitemap.xml"))
        if req.url.path == "/post/dcb37b06-8e05-434d-ac22-372a4c04cefc":
            return httpx.Response(200, text=load_fixture("micro1/post.html"))
        return httpx.Response(404)  # the other two postings have been taken down

    return handle


def test_sitemap_then_posts(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Micro1(), site(load_fixture))
    assert len(pages) == 1 and len(pages[0]) == 1  # the site root is not a post, 404s drop out
    job = pages[0][0]
    assert job.title == "Open Source Contributor" and job.company == "micro1"
    assert job.url == job.apply_url == POST
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-07-16T18:59:08"
    assert job.extra["micro1_id"] == "dcb37b06-8e05-434d-ac22-372a4c04cefc"
    assert "Rust" in job.extra["skills"]
    assert len(job.description) > 50  # the "$15" reference resolved to its text row


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(micro1, "CHUNK", 1)
    pages = search_pages(Micro1(), site(load_fixture))
    assert [len(p) for p in pages] == [1, 0, 0]
    assert search_pages(Micro1(), site(load_fixture), start_page=1) == [[], []]


def test_unreadable_or_closed_post(load_fixture: Callable[[str], Any]) -> None:
    html = load_fixture("micro1/post.html")
    assert parse_post("<html>nothing</html>", POST) is None
    assert (
        parse_post(
            html.replace('\\"job_status\\":\\"open\\"', '\\"job_status\\":\\"closed\\"'), POST
        )
        is None
    )
