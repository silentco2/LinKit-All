from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import pageup
from linkit_all.sources.ats.pageup import PageUp, parse_listing
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def make_handler(
    load_fixture: Callable[[str], Any], listing: str, calls: list[str] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if calls is not None:
            calls.append(str(req.url))
        # without the XHR header the site redirects to the full HTML page
        assert req.headers.get("X-Requested-With") == "XMLHttpRequest"
        if "/search/" in req.url.path:
            return httpx.Response(200, json={"results": load_fixture(f"pageup/{listing}")})
        return httpx.Response(200, json={"results": load_fixture("pageup/detail.html")})

    return handler


def test_three_tenant_layouts(load_fixture: Callable[[str], Any]) -> None:
    (a,) = parse_listing(load_fixture("pageup/table.html"), "513")  # bare <tr> rows, no <table>
    assert (a.title, a.location) == ("Senior Audiovisual Design Engineer", "Clayton campus")
    assert (
        a.url
        == "https://careers.pageuppeople.com/513/cw/en/job/694504/senior-audiovisual-design-engineer"
    )
    assert a.description == "Support the University's audiovisual design team."
    assert a.extra == {"board": "513", "id": "694504"}
    (b,) = parse_listing(load_fixture("pageup/list.html"), "391")  # <li> list
    assert (b.extra["id"], b.location) == ("980277", "Melbourne - Docklands")
    assert b.description == "Lead education and events programs."
    (c,) = parse_listing(load_fixture("pageup/card.html"), "709")  # unclassed summary paragraph
    assert (c.extra["id"], c.location) == ("501297", "Indonesia")
    assert c.description.startswith("Currently, Leighton Contractors Indonesia")


def test_summary_is_enough_no_detail_fetch(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    handler = make_handler(load_fixture, "table.html", calls)
    pages = search_pages(PageUp(), handler, board="513")
    assert pages[0][0].description == "Support the University's audiovisual design team."
    assert pages[0][0].ats == "pageup" and pages[0][0].company == "PageUp 513"
    assert len(calls) == 1 and "page-items=1000" in calls[0]


def test_detail_page_fills_a_missing_summary(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    handler = make_handler(load_fixture, "no_summary.html", calls)
    pages = search_pages(PageUp(), handler, board="798")
    (job,) = pages[0]
    assert (
        "Own the delivery of trading systems." in job.description
        and "Lead a team" in job.description
    )
    assert len(calls) == 2 and calls[1].endswith(
        "/798/cw/en/job/496049/senior-application-development-manager"
    )


def test_teaser_board_always_fetches_the_detail(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(PageUp(), make_handler(load_fixture, "teaser.html"), board="889")
    assert "Own the delivery" in pages[0][0].description  # the page body replaced the blurb


def test_fetch_details_only_when_missing(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="pageup",
        url="https://careers.pageuppeople.com/798/cw/en/job/496049/x",
        title="t",
        company="c",
    )
    full = fetch_details(PageUp(), make_handler(load_fixture, "table.html"), stub)
    assert "trading systems" in full.description
    done = stub.model_copy(update={"description": "kept"})
    assert fetch_details(PageUp(), lambda r: httpx.Response(500), done).description == "kept"


def test_chunks_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pageup, "CHUNK", 1)
    handler = make_handler(load_fixture, "table.html")
    assert len(search_pages(PageUp(), handler, board="513")) == 1
    assert search_pages(PageUp(), handler, board="513", start_page=1) == []


def test_bad_board_and_url_patterns(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="institution id"):
        search_pages(PageUp(), lambda r: httpx.Response(200), board="abc")
    assert detect("https://careers.pageuppeople.com/513/cw/en/listing/") == ("pageup", "513")
    assert detect("pageup:889") == ("pageup", "889")
