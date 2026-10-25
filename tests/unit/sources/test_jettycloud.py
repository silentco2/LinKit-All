from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.jettycloud import HOST, JettyCloud, editor_html


def handler_for(load_fixture: Callable[[str], Any]) -> Callable[[httpx.Request], httpx.Response]:
    pages = {
        "/vacancies": "jettycloud/listing.html",
        "/vacancies/site-reliability-engineer-telco-team": "jettycloud/vacancy.html",
        "/vacancies/go-developer": "jettycloud/closed.html",  # closed: 200 without a vacancy
    }

    def handler(req: httpx.Request) -> httpx.Response:
        path = req.url.path
        return (
            httpx.Response(200, text=load_fixture(pages[path]))
            if path in pages
            else httpx.Response(404)
        )

    return handler


def test_listing_anchors_then_apollo_cache(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(JettyCloud(), handler_for(load_fixture), board=HOST, calls=calls)
    fetched = [c for c in calls if "robots" not in c]
    assert fetched == [
        f"https://{HOST}/vacancies?",
        f"https://{HOST}/vacancies/site-reliability-engineer-telco-team",
        f"https://{HOST}/vacancies/go-developer",
    ]  # the grid icon in the CSS and the bare /vacancies link are not vacancies
    assert len(pages) == 1 and len(pages[0]) == 1  # the closed posting is left out
    job = pages[0][0]
    assert job.title == "Site Reliability Engineer (Telco team)" and job.company == "JettyCloud"
    assert job.url == f"https://{HOST}/vacancies/site-reliability-engineer-telco-team"
    assert job.extra["id"] == "490"  # not the related vacancy 489 sharing the cache
    for part in ("experienced", "What you will do", "Run things", "Fix <things>"):
        assert part in job.description


def test_empty_listing_fails(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    try:
        search_pages(
            JettyCloud(), lambda req: httpx.Response(200, text="<html></html>"), board=HOST
        )
    except ValueError as e:
        assert "markup changed" in str(e)
    else:
        raise AssertionError("an empty listing must fail, not read as no vacancies")


def test_editor_blocks() -> None:
    blocks = '[{"type":"header","data":{"text":"T","level":1}},{"type":"image","data":{}}]'
    assert (
        editor_html(blocks) == "<h3>T</h3>"
    )  # a level outside 2-4 is clamped, unknown blocks dropped
    assert editor_html("not json") == "" and editor_html("") == ""
    assert JettyCloud().tasks(SearchConfig())[0].board == HOST
