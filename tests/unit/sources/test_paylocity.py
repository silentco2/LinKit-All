from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import paylocity
from linkit_all.sources.ats.paylocity import Paylocity, description_of
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BOARD = "1a06dc72-45ee-4c90-a268-fe881bbeb577"


def make_handler(
    load_fixture: Callable[[str], Any], broken: str = ""
) -> Callable[[httpx.Request], httpx.Response]:
    """`broken`: the id whose details page answers 500."""

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if path == "/robots.txt":
            return httpx.Response(404)
        if path.startswith("/Recruiting/Jobs/All/"):
            return httpx.Response(200, text=load_fixture("paylocity/listing.html"))
        if broken and path.endswith(broken):
            return httpx.Response(500)
        return httpx.Response(200, text=load_fixture("paylocity/detail.html"))

    return handler


def test_listing_blob_then_details(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Paylocity(), make_handler(load_fixture), board=BOARD)
    tech, vet, manager = pages[0]
    assert tech.title == "Technician Aide" and tech.location == "CBAH - Airport Rd."
    assert tech.url == "https://recruiting.paylocity.com/Recruiting/Jobs/Details/4026535"
    assert tech.remote is None and tech.ats == "paylocity"
    assert "Care for animals" in tech.description and "alert" not in tech.description
    assert "Full-time" not in tech.description  # the Description block, not the first header
    # 11:55:56-05:00 is 16:55:56 UTC
    assert tech.posted_at is not None and tech.posted_at.isoformat() == "2026-06-29T16:55:56"
    assert tech.extra == {"board": BOARD, "id": "4026535"}
    assert vet.remote == "remote" and manager.remote == "hybrid"
    assert manager.title == "Practice Manager {lead}"  # braces inside strings do not end the array


def test_unreadable_details_page_keeps_the_job(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(Paylocity(), make_handler(load_fixture, "3836522"), board=BOARD)
    tech, vet, _ = pages[0]
    assert tech.description and vet.title == "Associate Veterinarian" and vet.description == ""


def test_description_falls_back_to_the_job_posting(load_fixture: Callable[[str], Any]) -> None:
    assert description_of(load_fixture("paylocity/detail_ld.html")) == "From the JobPosting block."
    assert description_of("<html></html>") == ""


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(paylocity, "CHUNK", 2)
    handler = make_handler(load_fixture)
    assert [len(p) for p in search_pages(Paylocity(), handler, board=BOARD)] == [2, 1]
    assert [len(p) for p in search_pages(Paylocity(), handler, board=BOARD, start_page=1)] == [1]


def test_listing_without_jobs_array_and_bad_board(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if "robots" in req.url.path else 200, text="<html></html>")

    with pytest.raises(ValueError, match="no Jobs array"):
        search_pages(Paylocity(), handler, board=BOARD)
    with pytest.raises(ValueError, match="company guid"):
        search_pages(Paylocity(), handler, board="acme")


def test_url_patterns() -> None:
    url = f"https://recruiting.paylocity.com/recruiting/jobs/All/{BOARD}/Clover-Basin"
    assert detect(url) == ("paylocity", BOARD)
    assert detect(f"paylocity:{BOARD}") == ("paylocity", BOARD)
