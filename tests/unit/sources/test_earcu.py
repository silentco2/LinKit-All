from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.earcu import Earcu
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub

BOARD = "careers.cambridge.org"


def _robots_ok(req: httpx.Request) -> httpx.Response | None:
    return httpx.Response(404) if req.url.path == "/robots.txt" else None


def test_search_reads_the_rss_feed(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    feed = load_fixture("earcu/rss.xml")
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        return _robots_ok(req) or httpx.Response(200, content=feed.encode())

    pages = search_pages(Earcu(), handler, board=BOARD, calls=calls)
    assert f"https://{BOARD}/jobs/rss" in calls
    assert len(pages) == 1 and len(pages[0]) == 2  # the item without a posting id is dropped
    first, second = pages[0]
    assert first.title == "Transfer Pricing Manager"  # reference suffix stripped
    assert first.company == "Cambridge" and first.location == "Cambridge"
    assert first.url.endswith("/transfer-pricing-manager-cambridge/7384/description/")
    assert "Build the finance pipeline." in first.description
    assert "Business Unit" not in first.description  # metadata prefix is not the body
    assert first.posted_at is not None and (first.posted_at.month, first.posted_at.day) == (7, 7)
    assert first.extra == {"board": BOARD, "id": "7384"} and first.ats == "earcu"
    assert second.location == "Remote" and second.remote == "remote"
    assert second.description == "" and second.posted_at is not None  # unpadded day parsed
    assert search_pages(Earcu(), handler, board=BOARD, start_page=1) == []


def test_fetch_details_falls_back_to_json_ld(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    page = load_fixture("earcu/detail.html")

    def handler(req: httpx.Request) -> httpx.Response:
        return _robots_ok(req) or httpx.Response(200, text=page)

    bare = JobStub(source="earcu", url=f"https://{BOARD}/jobs/vacancy/x/7375/description/",
                   title="t", company="c")  # fmt: skip
    assert fetch_details(Earcu(), handler, bare).description == "Work from anywhere."
    done = bare.model_copy(update={"description": "kept"})
    assert fetch_details(Earcu(), handler, done).description == "kept"


def test_url_patterns() -> None:
    vacancy = (
        "https://careers.cambridge.org/jobs/vacancy/transfer-pricing-manager/7384/description/"
    )
    assert detect(vacancy) == ("earcu", BOARD)
    assert detect(f"https://{BOARD}/jobs/rss") == ("earcu", BOARD)
    assert detect(f"earcu:{BOARD}") == ("earcu", BOARD)
