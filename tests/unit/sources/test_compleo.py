from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.compleo import Compleo
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_search_takes_only_the_boards_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    sitemap, job = load_fixture("compleo/sitemap.xml"), load_fixture("compleo/job.html")
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/sitemap.xml":
            return httpx.Response(200, text=sitemap)
        if req.url.path.endswith("HJ06277B"):
            return httpx.Response(404)  # closed since the sitemap was written
        return httpx.Response(200, text=job)

    pages = search_pages(Compleo(), handler, board="wafx", calls=calls)
    assert [u for u in calls if "jobdetail" in u] == [
        "https://jobs.compleo.app/wafx/jobdetail/HJ06276A",
        "https://jobs.compleo.app/wafx/jobdetail/HJ06277B",
    ]  # not wafxpro, agiliza or /home
    assert len(pages) == 1 and len(pages[0]) == 1
    j = pages[0][0]
    assert j.title == "Java Tech Lead - Lisboa" and j.company.startswith("WA FENIX")
    assert j.url == "https://jobs.compleo.app/wafx/jobdetail/HJ06276A"
    assert j.location == "PT" and "Java & Spring." in j.description and "alert" not in j.description
    assert j.posted_at is not None and j.posted_at.day == 25 and j.ats == "compleo"
    assert j.extra == {"employment": None, "valid_through": None, "board": "wafx", "id": "HJ06276A"}


def test_resume_skips_done_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    sitemap = load_fixture("compleo/sitemap.xml")

    def handler(req: httpx.Request) -> httpx.Response:
        text = sitemap if req.url.path == "/sitemap.xml" else ""
        return httpx.Response(404 if req.url.path == "/robots.txt" else 200, text=text)

    assert search_pages(Compleo(), handler, board="wafx", start_page=1) == []


def test_url_patterns() -> None:
    url = "https://jobs.compleo.app/wafx/jobdetail/HJ06276A"
    assert detect(url) == ("compleo", "wafx")
    assert detect("compleo:wafx") == ("compleo", "wafx")
