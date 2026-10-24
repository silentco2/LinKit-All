from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.keka import Keka
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_active_postings_and_organisation_name(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/careerportalinfo"):
            return httpx.Response(200, json=load_fixture("keka/portal_info.json"))
        return httpx.Response(200, json=load_fixture("keka/active.json"))

    pages = search_pages(Keka(), handler, board="minfy", calls=calls)
    assert "https://minfy.keka.com/careers/api/jobs/default/active" in calls
    assert len(pages) == 1 and len(pages[0]) == 2
    a, b = pages[0]
    assert a.title == "Senior Data Engineer" and a.company == "Minfy Technologies"
    assert a.url == "https://minfy.keka.com/careers/jobdetails/101"
    assert a.location == "Hyderabad, Telangana, India" and a.description == "Build pipelines."
    assert a.posted_at is not None and a.posted_at.isoformat() == "2026-09-01T09:30:00"
    assert a.extra == {"board": "minfy", "id": "101", "employment": "full_time"}
    assert a.ats == "keka" and a.remote is None
    assert b.remote == "remote" and b.location == "" and b.extra["employment"] == "part_time"


def test_a_missing_organisation_name_does_not_stop_the_board(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/careerportalinfo"):
            return httpx.Response(404)
        return httpx.Response(200, json=load_fixture("keka/active.json"))

    pages = search_pages(Keka(), handler, board="acme-corp")
    assert pages[0][0].company == "Acme Corp"


def test_resume_past_the_single_page_and_bad_answers(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    import pytest

    assert (
        search_pages(Keka(), lambda r: httpx.Response(200, json=[]), board="x", start_page=1) == []
    )
    with pytest.raises(ValueError, match="unexpected answer"):
        search_pages(Keka(), lambda r: httpx.Response(200, json={"error": "x"}), board="x")


def test_url_patterns() -> None:
    assert detect("https://minfy.keka.com/careers") == ("keka", "minfy")
    assert detect("https://minfy.keka.com/careers/jobdetails/101") == ("keka", "minfy")
    assert detect("keka:minfy") == ("keka", "minfy")
    assert detect("https://www.keka.com/pricing") is None
