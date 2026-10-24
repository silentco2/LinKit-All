from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.gupy import Gupy
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_search_maps_the_listing(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Gupy(),
        lambda req: httpx.Response(200, json=load_fixture("gupy/list.json")),
        board="origoenergiainterno",
        calls=calls,
    )
    assert calls == [
        "https://private-api.gupy.io/job-publication/public/jobs?subdomain=origoenergiainterno"
    ]
    assert len(pages) == 1 and len(pages[0]) == 2
    front, analyst = pages[0]
    assert front.title == "Pessoa Desenvolvedora FrontEnd Sênior"
    assert front.url == "https://origoenergiainterno.gupy.io/jobs/12691526"
    assert front.company == "Origoenergiainterno" and front.remote == "remote"
    assert front.location == "Brasil"
    assert analyst.location == "São Paulo, SP, Brasil" and analyst.remote == "hybrid"
    assert analyst.extra["id"] == "12679978" and analyst.ats == "gupy"
    assert analyst.description == ""  # only the detail has a body


def test_resume_past_the_single_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(
        Gupy(),
        lambda req: httpx.Response(200, json=load_fixture("gupy/list.json")),
        board="caju",
        start_page=1,
    )
    assert pages == []


def test_details_join_sections_and_drop_placeholders(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = Gupy.stub({"id": 12679978, "name": "Analista"}, "origoenergiainterno")
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req.url.path)
        return httpx.Response(200, json=load_fixture("gupy/detail_12679978.json"))

    out = fetch_details(Gupy(), handler, stub)
    assert seen == ["/job-publication/public/jobs/12679978"]
    assert out.description.startswith("“Na Órigo Energia")
    assert "<p" not in out.description and "style=" not in out.description
    assert out.posted_at is not None and (out.posted_at.year, out.posted_at.month) == (2026, 10)


def test_details_of_a_vanished_posting_leave_the_stub(
    fetch_details: Callable[..., JobStub],
) -> None:
    stub = Gupy.stub({"id": 1, "name": "Gone"}, "caju")
    assert fetch_details(Gupy(), lambda req: httpx.Response(404), stub) == stub


def test_url_patterns_skip_gupys_own_hosts() -> None:
    assert detect("https://caju.gupy.io/") == ("gupy", "caju")
    assert detect("https://origoenergiainterno.gupy.io/jobs/12679978") == (
        "gupy",
        "origoenergiainterno",
    )
    assert detect("https://private-api.gupy.io/job-publication/public/jobs") is None
    assert detect("https://portal.gupy.io/job-search") is None
