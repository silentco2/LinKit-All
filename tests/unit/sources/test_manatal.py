from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.manatal import Manatal
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def make_handler(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        page = req.url.params.get("page", "1")
        return httpx.Response(200, json=load_fixture(f"manatal/page{page}.json"))

    return handler


def test_follows_the_next_link(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Manatal(), make_handler(load_fixture), board="davidjoseph-co", calls=calls)
    assert calls == [
        "https://open.api.manatal.com/open/v3/career-page/davidjoseph-co/jobs/",
        "https://open.api.manatal.com/open/v3/career-page/davidjoseph-co/jobs/?page=2",
    ]
    assert [[j.title for j in p] for p in pages] == [
        ["Recruitment Consultant", "Remote Researcher"],  # the posting without a hash is dropped
        ["Office Manager"],
    ]
    a, b = pages[0]
    assert a.url == "https://www.careers-page.com/davidjoseph-co/job/a1b2c3"
    assert a.company == "Davidjoseph Co" and a.location == "London, England, United Kingdom"
    assert a.description == "Place people." and a.posted_at is None and a.ats == "manatal"
    assert a.extra == {"board": "davidjoseph-co", "id": "a1b2c3", "employment": "full_time"}
    assert b.remote == "remote" and b.location == ""
    assert pages[1][0].location == "Leeds, United Kingdom"  # built from the parts


def test_resume_starts_at_the_requested_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Manatal(), make_handler(load_fixture), board="davidjoseph-co", start_page=1, calls=calls
    )
    assert calls == ["https://open.api.manatal.com/open/v3/career-page/davidjoseph-co/jobs/?page=2"]
    assert [j.title for p in pages for j in p] == ["Office Manager"]


def test_page_limit_stops_a_feed_that_never_ends(
    search_pages: Callable[..., list[list[JobStub]]], monkeypatch: Any
) -> None:
    from linkit_all.sources.ats import manatal

    monkeypatch.setattr(manatal, "MAX_PAGES", 3)
    loop = {
        "next": "https://open.api.manatal.com/open/v3/career-page/x/jobs/?page=2",
        "results": [],
    }
    pages = search_pages(Manatal(), lambda req: httpx.Response(200, json=loop), board="x")
    assert len(pages) == 3


def test_url_patterns() -> None:
    assert detect("https://www.careers-page.com/davidjoseph-co") == ("manatal", "davidjoseph-co")
    assert detect("https://www.careers-page.com/davidjoseph-co/job/a1b2c3") == (
        "manatal",
        "davidjoseph-co",
    )
    assert detect("manatal:davidjoseph-co") == ("manatal", "davidjoseph-co")
