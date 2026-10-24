from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.jobscore import JobScore
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_feed_maps_every_field(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    feed = load_fixture("jobscore/feed.json")
    calls: list[str] = []
    pages = search_pages(
        JobScore(),
        lambda req: httpx.Response(200, json=feed),
        board="ierustechnologiesinc",
        calls=calls,
    )
    assert calls == [
        "https://careers.jobscore.com/jobs/ierustechnologiesinc/feed.json?sort=date&limit=1000"
    ]
    assert len(pages) == 1 and len(pages[0]) == 3  # the posting without an id is dropped
    a, b, c = pages[0]
    assert a.title == "Systems and Network Administrator"
    assert a.url == (
        "https://careers.jobscore.com/careers/ierustechnologiesinc/jobs/"
        "systems-and-network-administrator-dgLTVq3fbbbkS61af48PpK"
    )  # tracking query dropped
    assert a.company == "IERUS Technologies, Inc." and a.location == "Huntsville, AL"
    assert a.remote == "onsite" and a.ats == "jobscore" and a.apply_url == a.url
    assert a.description == "IERUS specializes in RF."
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-03-31T17:04:28.293000"
    assert a.extra["id"] == "dgLTVq3fbbbkS61af48PpK" and a.extra["employment"] == "Full Time"
    assert b.remote == "remote" and b.location == "Remote in Joinville, Santa Catarina, Brazil"
    assert b.posted_at is not None and b.posted_at.date().isoformat() == "2026-05-01"
    assert c.remote == "hybrid" and c.location == "US"
    assert c.url == "https://careers.jobscore.com/careers/ierustechnologiesinc/jobs/hyb7"


def test_company_falls_back_to_the_slug(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    feed = {"jobs": [{"id": "x1", "title": "Role", "description": "<p>d</p>"}]}
    pages = search_pages(JobScore(), lambda req: httpx.Response(200, json=feed), board="acme-corp")
    assert pages[0][0].company == "Acme Corp"


def test_resume_past_the_single_page_yields_nothing(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    calls: list[str] = []
    pages = search_pages(
        JobScore(), lambda req: httpx.Response(200, json={}), board="x", start_page=1, calls=calls
    )
    assert pages == [] and calls == []


def test_url_patterns() -> None:
    page = "https://careers.jobscore.com/careers/ierustechnologiesinc"
    assert detect(page) == ("jobscore", "ierustechnologiesinc")
    assert detect(page + "/jobs/some-role-abc123?ref=rss") == ("jobscore", "ierustechnologiesinc")
    assert detect("https://careers.jobscore.com/jobs/acme/feed.json") == ("jobscore", "acme")
    assert detect("jobscore:acme") == ("jobscore", "acme")
