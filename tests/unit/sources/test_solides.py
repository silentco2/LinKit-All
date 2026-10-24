from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.solides import Solides
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def _serve(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["slug"] == "dynamox" and req.url.params["take"] == "25"
        return httpx.Response(200, json=load_fixture(f"solides/page{req.url.params['page']}.json"))

    return handler


def test_search_pages_and_maps(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(Solides(), _serve(load_fixture), board="dynamox", calls=calls)
    assert len(calls) == 2 and [len(p) for p in pages] == [1, 1]  # the closed vacancy is dropped
    be, sre = pages[0][0], pages[1][0]
    assert be.title == "Backend Engineer" and be.company == "Dynamox"
    assert be.url == "https://dynamox.vagas.solides.com.br/vaga/2001" and be.apply_url == be.url
    assert be.location == "Florianópolis, SC" and be.remote == "hybrid"
    assert "Build things" in be.description and "evil" not in be.description
    assert be.posted_at is not None and be.posted_at.date().isoformat() == "2026-06-11"
    assert be.extra == {"board": "dynamox", "id": "2001"} and be.ats == "solides"
    assert sre.remote == "remote" and sre.location == ""


def test_resume_starts_at_the_given_page(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Solides(), _serve(load_fixture), board="dynamox", start_page=1, calls=calls
    )
    assert len(calls) == 1 and pages[0][0].title == "Remote SRE"


def test_error_raises(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(httpx.HTTPStatusError):
        search_pages(Solides(), lambda req: httpx.Response(404), board="nobody")


def test_url_patterns() -> None:
    assert detect("https://dynamox.vagas.solides.com.br/vaga/2001") == ("solides", "dynamox")
    assert detect("solides:dynamox") == ("solides", "dynamox")
