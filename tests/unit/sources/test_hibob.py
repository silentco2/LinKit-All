from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.hibob import HiBob
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_search_sends_the_tenant_referer_and_maps_ads(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("hibob/job_ad.json"))

    pages = search_pages(HiBob(), handler, board="qogita")
    assert [str(r.url) for r in seen] == ["https://qogita.careers.hibob.com/api/job-ad"]
    assert seen[0].headers["Referer"] == "https://qogita.careers.hibob.com/jobs"
    assert len(pages) == 1 and len(pages[0]) == 2  # the id-less ad has no dedup key
    ds, agent = pages[0]
    assert ds.title == "Data Scientist, Client Facing" and ds.company == "Qogita"
    assert ds.url == "https://qogita.careers.hibob.com/jobs/04e764ae-fb6c-4303-ba2f-509b917804c2"
    assert ds.location == "New York, United States" and ds.remote == "hybrid"
    assert ds.posted_at is not None and ds.posted_at.date().isoformat() == "2026-04-22"
    assert ds.extra["id"] == "04e764ae-fb6c-4303-ba2f-509b917804c2" and ds.ats == "hibob"
    assert agent.remote == "remote"


def test_description_keeps_the_sections_apart_and_sanitised(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(
        HiBob(), lambda req: httpx.Response(200, json=load_fixture("hibob/job_ad.json")), board="q"
    )
    text = pages[0][0].description
    assert text.startswith("We build AI & finance tooling.")
    assert "alert" not in text
    assert "Responsibilities\nWork on-site with clients" in text
    assert "Requirements\n4+ years as a data scientist" in text
    assert text.endswith("Benefits\n$140-170k DOE")
    assert pages[0][1].description == "Answer tickets."  # empty sections add no headings


def test_resume_and_url_patterns(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = lambda req: httpx.Response(200, json=load_fixture("hibob/job_ad.json"))  # noqa: E731
    assert search_pages(HiBob(), handler, board="q", start_page=1) == []
    assert detect("https://qogita.careers.hibob.com/jobs/04e764ae") == ("hibob", "qogita")
