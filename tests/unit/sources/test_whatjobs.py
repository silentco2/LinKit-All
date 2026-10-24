from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._keyed import parse_ids, split_location
from linkit_all.sources.aggregators.whatjobs import WhatJobs
from linkit_all.sources.base import JobStub
from linkit_all.sources.careers import Unsupported


def keys(name: str) -> dict[str, str] | None:
    return {"publisher_ids": "us=7065, uk:7066 , broken"} if name == "whatjobs" else None


def test_helpers_parse_ids_and_locations() -> None:
    assert parse_ids("gb=123, us:456 ,bad,=5") == {"gb": "123", "us": "456"}
    assert split_location("Leeds, UK") == ("gb", "Leeds")
    assert split_location("Egypt") == ("eg", "")
    assert split_location("Austin, TX") == (None, "Austin, TX")


def test_no_key_no_tasks_and_task_countries() -> None:
    cfg = SearchConfig.model_validate(
        {
            "search": {
                "queries": ["backend engineer"],
                "locations": ["New York, USA", "Cairo, Egypt"],
            }
        }
    )
    assert WhatJobs(keys=lambda n: None).tasks(cfg) == []
    assert WhatJobs().tasks(cfg) == []
    tasks = WhatJobs(keys=keys).tasks(cfg)
    assert [t.country for t in tasks] == ["us", "eg"]
    assert WhatJobs.parallel == 2


def test_search_sends_publisher_and_maps_stubs(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        data = load_fixture("whatjobs/page.json") if req.url.params["page"] == "1" else {"data": []}
        return httpx.Response(200, json=data)

    pages = search_pages(
        WhatJobs(keys=keys),
        handler,
        query="backend engineer",
        country="us",
        location="New York, USA",
    )
    q = seen[0].url.params
    assert (q["publisher"], q["keyword"], q["limit"], q["page"]) == (
        "7065",
        "backend engineer",
        "50",
        "1",
    )
    assert q["user_ip"] == "0.0.0.0"  # noqa: S104
    assert len(seen) == 2  # page 2 is empty
    (j,) = pages[0]
    assert j.title == "Lead Backend Engineer" and j.company == "Duolingo"
    assert j.location == "New York, United States"
    assert j.url.startswith("https://www.whatjobs.com/pub_api__cpl__2737655843__7065")
    assert j.extra == {"id": "2737655843", "country": "us"}
    assert j.description == "Own the scoring platform."  # the reseller tag is cut


def _posting(i: int, title: str) -> dict[str, str]:
    return {
        "title": title,
        "company": "Acme",
        "location": "Austin",
        "snippet": "<p>text</p>",
        "url": f"https://www.whatjobs.com/pub_api__cpl__{i}__7065",
    }


def test_stops_when_relevance_collapses_and_dedupes(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    served = {
        "1": [_posting(1, "Rust Engineer"), _posting(2, "Rust Developer")],
        "2": [_posting(2, "Rust Developer"), _posting(3, "Rust Lead"), _posting(4, "Nurse")],
        "3": [_posting(5, "Nurse"), _posting(6, "Driver"), _posting(7, "Rust Dev")],
        "4": [_posting(8, "Rust Dev")],
    }
    asked: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        asked.append(req.url.params["page"])
        return httpx.Response(200, json={"data": served.get(req.url.params["page"], [])})

    pages = search_pages(
        WhatJobs(keys=keys), handler, query="rust engineer", country="us", limit=100
    )
    # page 2 repeats job 2 and has one nurse; page 3 is 1 of 3 relevant (<50%): the crawl ends there
    assert [[s.extra["id"] for s in p] for p in pages] == [["1", "2"], ["3"], ["7"]]
    assert asked == ["1", "2", "3"]


def test_page_without_tracked_ids_is_an_error(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    bad = {"data": [{"title": "A", "url": "https://www.whatjobs.com/jobs/a-1"}]}
    with pytest.raises(RuntimeError, match="no tracked job ids"):
        search_pages(
            WhatJobs(keys=keys), lambda r: httpx.Response(200, json=bad), query="a", country="us"
        )


def test_country_without_publisher_id_is_unsupported(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    with pytest.raises(Unsupported, match="no WhatJobs publisher ID for Egypt"):
        search_pages(WhatJobs(keys=keys), boom, query="a", country="eg")
    with pytest.raises(Unsupported, match="needs a country"):
        search_pages(WhatJobs(keys=keys), boom, query="a", location="")
    # "uk" in the saved IDs counts as gb
    pages = search_pages(
        WhatJobs(keys=keys),
        lambda r: httpx.Response(200, json={"data": []}),
        query="a",
        country="gb",
    )
    assert pages == []
