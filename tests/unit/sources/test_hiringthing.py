from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import hiringthing
from linkit_all.sources.ats.hiringthing import HiringThing
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

HOST = "crown-shredding-llc.prismhr-hire.com"


def _handler(load_fixture: Callable[[str], Any], calls: list[str]) -> Any:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        calls.append(req.url.path)
        if req.url.path == "/":
            return httpx.Response(200, text=load_fixture("hiringthing/listing.html"))
        job_id = req.url.path.split("/")[2]
        return httpx.Response(200, text=load_fixture(f"hiringthing/job_{job_id}.html"))

    return handler


def test_listing_then_record_per_posting(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(HiringThing(), _handler(load_fixture, calls), board=HOST)
    # The card links its posting twice, a posting of another host is not ours, and an id inside
    # another link's query string names no posting.
    assert calls == ["/", "/job/952170/mobile-shred-operator", "/job/952171/driver"]
    assert len(pages) == 1
    shred, driver = pages[0]
    assert shred.title == "Mobile Shred Operator" and shred.company == "Crown Shredding Llc"
    assert shred.url == f"https://{HOST}/job/952170/mobile-shred-operator"
    assert shred.location == "Orlando, FL" and shred.remote is None
    assert shred.description == "Drive the\ntruck\n."
    assert "alert" not in shred.description
    assert shred.posted_at is not None and shred.posted_at.date().isoformat() == "2026-08-17"
    assert (shred.salary_min, shred.salary_max) == (18.5, 21.0)
    assert (shred.salary_currency, shred.salary_interval) == ("USD", "hour")
    assert shred.extra == {"board": HOST, "id": "952170"} and shred.ats == "hiringthing"
    assert driver.url == f"https://{HOST}/job/952171/driver"  # a relative link, made absolute
    assert driver.remote == "remote" and driver.location == "Remote - Windsor Locks, CT"
    assert driver.salary_min is None  # empty bounds state no pay, whatever the frequency


def test_a_bare_slug_lives_under_the_vendors_domain(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(404 if req.url.path == "/robots.txt" else 200, text="<html></html>")

    assert search_pages(HiringThing(), handler, board="skijapan") == []
    assert calls[-1] == "https://skijapan.hiringthing.com/"


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hiringthing, "CHUNK", 1)
    pages = search_pages(HiringThing(), _handler(load_fixture, []), board=HOST)
    assert [[s.title for s in p] for p in pages] == [["Mobile Shred Operator"], ["Driver"]]
    calls: list[str] = []
    pages = search_pages(HiringThing(), _handler(load_fixture, calls), board=HOST, start_page=1)
    assert [[s.title for s in p] for p in pages] == [["Driver"]]
    assert "/job/952170/mobile-shred-operator" not in calls


def test_record_is_found_by_component_name_and_may_be_absent() -> None:
    page = (
        '<div data-react-class="HiringThing.Components.CookieBanner" data-react-props="{}"></div>'
    )
    assert HiringThing.record(page) is None
    assert (
        HiringThing.record(
            '<div data-react-class="HiringThing.Components.ApplyButtonGroup" '
            'data-react-props="not json"></div>'
        )
        is None
    )


def test_job_links_and_url_patterns(load_fixture: Callable[[str], Any]) -> None:
    links = HiringThing.job_links(f"https://{HOST}/", load_fixture("hiringthing/listing.html"))
    assert [u.rsplit("/", 2)[-2] for u in links] == ["952170", "952171"]
    assert detect("https://skijapan.hiringthing.com/job/1052705/guest-services") == (
        "hiringthing",
        "skijapan.hiringthing.com",
    )
