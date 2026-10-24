import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from aiolimiter import AsyncLimiter

from linkit_all.sources.ats import taleo
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Http, "_limiter", lambda self, host: AsyncLimiter(1000, 1))


def _serve(
    load_fixture: Callable[[str], Any], seen: list[int] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/careersection/2/jobsearch.ftl":
            return httpx.Response(200, text=load_fixture("taleo/section.html"))
        if req.url.path == "/careersection/rest/jobboard/searchjobs":
            assert req.url.params["portal"] == "101430233" and req.headers["tz"] == "GMT+00:00"
            page = json.loads(req.content)["pageNo"]
            if seen is not None:
                seen.append(page)
            return httpx.Response(200, json=load_fixture(f"taleo/search{page}.json"))
        if req.url.path == "/careersection/2/jobdetail.ftl":
            return httpx.Response(200, text=load_fixture("taleo/detail.html"))
        return httpx.Response(404)

    return handler


def test_search_pages_and_maps(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[int] = []
    pages = search_pages(taleo.Taleo(), _serve(load_fixture, seen), board="valero.taleo.net/2")
    assert seen == [1, 2]  # totalCount 3 is reached on page 2 (2 a page)
    assert [len(p) for p in pages] == [2, 1]  # the row without a contest number is dropped
    health, remote, driver = pages[0] + pages[1]
    assert health.title == "Occupational Health Professional" and health.company == "Valero"
    assert (
        health.url == "https://valero.taleo.net/careersection/2/jobdetail.ftl?job=2600197&lang=en"
    )
    assert health.location == "US-OK-Ardmore" and health.ats == "taleo"
    assert health.posted_at is not None and health.posted_at.date().isoformat() == "2026-07-02"
    assert health.extra == {"board": "valero.taleo.net/2", "id": "2600197"}
    assert remote.location == "US-TX-San Antonio, US-CA-San Diego"  # multi-place cell
    assert driver.location == "" and driver.posted_at is None  # this tenant lists neither


def test_resume(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[int] = []
    pages = search_pages(
        taleo.Taleo(), _serve(load_fixture, seen), board="valero.taleo.net/2", start_page=1
    )
    assert seen == [2] and pages[0][0].title == "Dedicated truck driver"


def test_fetch_details_decodes_the_description(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="taleo",
        url="https://valero.taleo.net/careersection/2/jobdetail.ftl?job=2600197&lang=en",
        title="x",
        company="Valero",
    )
    done = fetch_details(taleo.Taleo(), _serve(load_fixture), stub)
    assert "Provide care." in done.description
    # a stray "%" (Word-pasted CSS) and "C++" survive; the script is gone
    assert "100% remote. C++" in done.description and "alert" not in done.description
    gone = fetch_details(taleo.Taleo(), lambda req: httpx.Response(404), stub)
    assert gone.description == ""


def test_description_without_the_marker_is_empty() -> None:
    assert taleo.description("<html><body>Nothing</body></html>") == ""
    assert taleo.description('<input name="initialHistory" value="a!|!b">') == ""


def test_bad_boards_and_pages_are_refused(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    with pytest.raises(Unsupported):
        search_pages(taleo.Taleo(), lambda req: httpx.Response(200), board="valero.taleo.net")
    with pytest.raises(Unsupported):  # no portal number: not a public careersection
        search_pages(
            taleo.Taleo(),
            lambda req: httpx.Response(200, text="<html></html>"),
            board="a.taleo.net/2",
        )


def test_url_patterns() -> None:
    url = "https://valero.taleo.net/careersection/2/jobdetail.ftl?job=2600197"
    assert detect(url) == ("taleo", "valero.taleo.net/2")
    assert detect("https://x.taleo.net/careersection/rest/jobboard/searchjobs") is None
    assert detect("taleo:valero.taleo.net/2") == ("taleo", "valero.taleo.net/2")
