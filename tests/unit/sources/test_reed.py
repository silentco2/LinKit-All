import base64
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators.reed import Reed
from linkit_all.sources.base import JobStub
from linkit_all.sources.careers import Unsupported

BASIC = "Basic " + base64.b64encode(b"reed-key-123:").decode()


def keys(name: str) -> dict[str, str] | None:
    return {"api_key": "reed-key-123"} if name == "reed" else None


def test_no_key_no_tasks() -> None:
    cfg = SearchConfig.model_validate({"search": {"queries": ["python"]}})
    assert Reed(keys=lambda n: None).tasks(cfg) == []
    assert Reed().tasks(cfg) == []
    assert [t.query for t in Reed(keys=keys).tasks(cfg)] == ["python"]


def test_search_uses_basic_auth_and_maps_stubs(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("reed/reed_search.json"))

    pages = search_pages(
        Reed(keys=keys),
        handler,
        query="software engineer",
        location="Manchester, UK",
        limit=100,
    )
    (req,) = seen  # limit=100: one page is enough
    assert req.headers["Authorization"] == BASIC
    q = req.url.params
    assert (q["keywords"], q["locationName"], q["resultsToTake"]) == (
        "software engineer",
        "Manchester",
        "100",
    )
    assert q["resultsToSkip"] == "0"
    a, b = pages[0]
    assert (a.title, a.company, a.location) == ("Software Engineer", "Moorepay", "Manchester")
    assert a.url == "https://www.reed.co.uk/jobs/software-engineer/56785467"
    assert a.description == "" and a.posted_at is not None and a.posted_at.month == 4
    assert b.company == "Matchtech"  # trailing space trimmed
    assert a.extra["id"] == "56785467" and a.ats == "reed"


def test_paging_stops_at_total_and_resumes(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    item = load_fixture("reed/reed_search.json")["results"][0]
    skips: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        skip = int(req.url.params["resultsToSkip"])
        skips.append(str(skip))
        results = [{**item, "jobId": skip + i + 1} for i in range(100)] if skip < 250 else []
        return httpx.Response(200, json={"totalResults": 250, "results": results})

    pages = search_pages(Reed(keys=keys), handler, query="x", limit=1000, start_page=1)
    assert skips == ["100", "200"] and [len(p) for p in pages] == [100, 100]


def test_non_uk_location_unsupported(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(Unsupported, match="UK jobs only"):
        search_pages(
            Reed(keys=keys), lambda r: httpx.Response(500), query="x", location="Cairo, Egypt"
        )


def test_fetch_details_reads_full_body_with_key(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=load_fixture("reed/reed_job.json"))

    stub = JobStub(
        source="reed",
        url="https://www.reed.co.uk/jobs/hgv-class-2-driver/57029285",
        title="HGV Class 2 Driver",
        company="Tesco",
    )
    out = fetch_details(Reed(keys=keys), handler, stub)
    assert (
        seen[0].url.path == "/api/1.0/jobs/57029285" and seen[0].headers["Authorization"] == BASIC
    )
    assert "Fully funded CPC training" in out.description and "<p>" not in out.description
    assert (
        out.apply_url
        == "https://careers.tesco.com/en_GB/careers/JobDetail/HGV-Class-2-Driver/190529"
    )
    # no key (vault locked): the stub is returned untouched, no request is made
    same = fetch_details(Reed(keys=lambda n: None), lambda r: httpx.Response(500), stub)
    assert same == stub
