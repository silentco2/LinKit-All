from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.jobvite import Jobvite
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path == "/hbg/jobs":
            return httpx.Response(200, text=load_fixture("jobvite/listing.html"))
        if path in ("/hbg/job/ojJpAfwL", "/hbg/job/ode8zfwS"):
            return httpx.Response(
                200, text=load_fixture(f"jobvite/detail_{path.rsplit('/', 1)[1]}.html")
            )
        return httpx.Response(404)

    return handler


def test_listing_then_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Jobvite(), make_handler(load_fixture), board="hbg", calls=calls)
    assert "https://jobs.jobvite.com/hbg/jobs" in calls
    assert len(pages) == 1
    # The duplicate link and the nav links are not postings; the gone one (404) is dropped.
    assert [j.title for j in pages[0]] == ["Editorial Assistant", "Remote Designer"]
    a, b = pages[0]
    assert a.url == "https://jobs.jobvite.com/hbg/job/ojJpAfwL"
    assert a.company == "Hachette Book Group" and a.location == "New York, United States"
    assert a.description == "Build books." and a.ats == "jobvite"
    assert a.posted_at is not None and a.posted_at.date().isoformat() == "2026-06-30"
    assert a.extra["id"] == "ojJpAfwL" and a.extra["board"] == "hbg"
    assert b.url == "https://jobs.jobvite.com/hbg/job/ode8zfwS"  # ?nl=1 is not part of the page
    assert b.company == "Hbg"  # no hiringOrganization: the slug names it
    assert b.location == "Remote, United States" and b.remote == "remote"


def test_resume_skips_earlier_chunks(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    assert search_pages(Jobvite(), make_handler(load_fixture), board="hbg", start_page=1) == []


def test_fetch_details(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="jobvite",
        url="https://jobs.jobvite.com/hbg/job/ojJpAfwL",
        title="t",
        company="c",
        extra={"board": "hbg"},
    )
    full = fetch_details(Jobvite(), make_handler(load_fixture), stub)
    assert full.description == "Build books."


def test_url_patterns() -> None:
    assert detect("https://jobs.jobvite.com/hbg/jobs") == ("jobvite", "hbg")
    assert detect("https://jobs.jobvite.com/hbg/job/ojJpAfwL") == ("jobvite", "hbg")
    assert detect("https://jobs.jobvite.com/careers/acme-co/jobs") == ("jobvite", "acme-co")
    assert detect("jobvite:hbg") == ("jobvite", "hbg")
