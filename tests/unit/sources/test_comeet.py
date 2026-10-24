from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats.comeet import Comeet
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_search_reads_token_then_positions(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    page, positions = (
        load_fixture("comeet/careers_page.html"),
        load_fixture("comeet/positions.json"),
    )
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.host == "www.comeet.com":
            return httpx.Response(200, text=page)
        assert req.url.params["token"] == "1B16C4BD7005131B1A26F391B1"  # noqa: S105
        return httpx.Response(200, json=positions)

    pages = search_pages(Comeet(), handler, board="overwolf/B1.001", calls=calls)
    assert len(pages) == 1 and len(pages[0]) == 1  # the position without a uid is dropped
    job = pages[0][0]
    assert job.title == "Data Analyst Lead" and job.company == "Overwolf"
    assert job.url == "https://careers.overwolf.com/career/BC.26F"
    assert job.location == "Ramat Gan, Israel" and job.remote == "hybrid"
    assert "Lead our data team." in job.description and "SQL" in job.description
    assert "Requirements" in job.description and "alert" not in job.description
    assert job.posted_at is not None and job.posted_at.year == 2026
    assert job.extra == {"board": "overwolf/B1.001", "id": "BC.26F"}
    assert any("/company/B1.001/positions" in c for c in calls)


def test_missing_token_and_bad_board(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(404 if req.url.path == "/robots.txt" else 200, text="<html></html>")

    with pytest.raises(ValueError, match="no API token"):
        search_pages(Comeet(), handler, board="overwolf/B1.001")
    with pytest.raises(ValueError, match="must be"):
        search_pages(Comeet(), handler, board="overwolf")


def test_url_patterns() -> None:
    assert detect("https://www.comeet.com/jobs/overwolf/B1.001") == ("comeet", "overwolf/B1.001")
    assert detect("see www.comeet.com/jobs/acme/12.345/ for jobs") == ("comeet", "acme/12.345")
    assert detect("comeet:overwolf/B1.001") == ("comeet", "overwolf/B1.001")
