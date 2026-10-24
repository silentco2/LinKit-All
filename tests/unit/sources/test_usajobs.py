from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators.usajobs import USAJobs
from linkit_all.sources.base import JobStub
from linkit_all.sources.careers import Unsupported

KEYS = {"api_key": "usa-key-1", "email": "me@example.com"}


def keys(name: str) -> dict[str, str] | None:
    return KEYS if name == "usajobs" else None


def test_no_key_no_tasks() -> None:
    cfg = SearchConfig.model_validate({"search": {"queries": ["developer"]}})
    assert USAJobs(keys=lambda n: None).tasks(cfg) == []
    assert USAJobs(keys=lambda n: {"api_key": "k"}).tasks(cfg) == []  # needs the email too
    assert [t.key for t in USAJobs(keys=keys).tasks(cfg)] == ["usajobs:developer:"]


def test_search_sends_key_and_email_headers_and_maps_stubs(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("usajobs/usajobs_search.json"))

    pages = search_pages(
        USAJobs(keys=keys), handler, query="developer", location="Denver, CO", posted_within_days=90
    )
    (req,) = seen
    assert req.headers["Authorization-Key"] == "usa-key-1"
    assert req.headers["User-Agent"] == "me@example.com"
    q = req.url.params
    assert (q["Keyword"], q["LocationName"], q["ResultsPerPage"], q["Page"]) == (
        "developer",
        "Denver, CO",
        "500",
        "1",
    )
    assert q["DatePosted"] == "60"  # the API's maximum
    a, b = pages[0]
    assert a.title == "Information Technology Specialist (Applications Software)"
    assert (a.company, a.location) == ("Internal Revenue Service", "Anchorage, Alaska")
    assert a.url == "https://www.usajobs.gov/job/871922900"  # the :443 is dropped
    assert a.remote == "hybrid"  # telework eligible, not remote
    assert (a.salary_min, a.salary_max, a.salary_currency, a.salary_interval) == (
        89508.0,
        145468.0,
        "USD",
        "year",
    )
    assert "Additional jobs may be filled" in a.description and "STANDARD POSITION" in a.description
    assert a.posted_at is not None and (a.posted_at.month, a.posted_at.day) == (6, 5)
    assert b.company == "Naval Sea Systems Command" and a.extra["id"] == "871922900"


def test_paging_until_short_page(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    def item(i: int) -> dict[str, Any]:
        return {
            "MatchedObjectId": str(i),
            "MatchedObjectDescriptor": {"PositionTitle": "T", "OrganizationName": "Org"},
        }

    def handler(req: httpx.Request) -> httpx.Response:
        n = 500 if req.url.params["Page"] == "1" else 3
        body = {"SearchResult": {"SearchResultItems": [item(i) for i in range(n)]}}
        return httpx.Response(200, json=body)

    pages = search_pages(USAJobs(keys=keys), handler, query="x", limit=1000)
    assert [len(p) for p in pages] == [500, 3]
    pages = search_pages(USAJobs(keys=keys), handler, query="x", limit=200)
    assert [len(p) for p in pages] == [500]  # the limit is reached after the first page


def test_non_us_location_unsupported(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(Unsupported, match="US federal"):
        search_pages(
            USAJobs(keys=keys), lambda r: httpx.Response(500), query="x", location="Leeds, UK"
        )
