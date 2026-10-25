import json
from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies import ibm
from linkit_all.sources.companies.ibm import HOST, Ibm, description, location


def test_search_posts_the_named_fields_and_maps_hits(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(req.content))
        return httpx.Response(200, json=load_fixture("ibm/ibm_search_italy.json"))

    pages = search_pages(Ibm(), handler, board=HOST)
    b = bodies[0]
    assert b["size"] == 100 and b["from"] == 0 and b["sort"] == [{"id": "asc"}]
    assert "field_text_01" in b["_source"] and "body" in b["_source"]
    assert len(pages) == 1 and len(pages[0]) == 3
    intern, dba, bari = pages[0]
    assert intern.title == "Internship Cloud FullStack Developer" and intern.company == "IBM"
    assert intern.url == "https://careers.ibm.com/careers/JobDetail?jobId=136943"
    assert intern.location == "Italy" and intern.remote == "hybrid"  # "Multiple Cities"
    assert intern.posted_at is not None and intern.posted_at.date().isoformat() == "2026-10-13"
    assert intern.extra["level"] == "Internship" and intern.extra["id"] == "136943"
    assert bari.location == "Bari, Italy"
    # the facet values the index appends after the text are cut, the bullets get their own lines
    assert not intern.description.endswith("IBM Client Innovation Center Milano S.r.l")
    assert "\n• knowledge of the java programming language\n• SQL" in intern.description
    assert dba.description.endswith("communication skills")


def test_paging_by_from_and_resume(
    search_pages: Callable[..., list[list[JobStub]]], monkeypatch: Any
) -> None:
    monkeypatch.setattr(ibm, "PAGE", 2)
    starts: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        start = json.loads(req.content)["from"]
        starts.append(start)
        hits = [
            {"_source": {"field_text_01": i + 1, "title": f"J{i}", "body": f"text {i}"}}
            for i in range(start, min(start + 2, 3))
        ]
        return httpx.Response(200, json={"hits": {"total": {"value": 3}, "hits": hits}})

    pages = search_pages(Ibm(), handler, board=HOST)
    assert starts == [0, 2] and [len(p) for p in pages] == [2, 1]
    starts.clear()
    search_pages(Ibm(), handler, board=HOST, start_page=1)
    assert starts == [2]


def test_location_and_description_helpers() -> None:
    assert location("BUDAPEST, HU", "Hungary") == "Budapest, Hungary"
    assert location("Multiple Cities", "Italy") == "Italy"
    assert location("Remote Hub", "Italy") == "Remote Hub"
    body = "You\u2019ll lead\xa0•\xa0build  • test Italy Consulting Hybrid Professional Milan, IT (1) IBM"
    p = {
        "body": body.replace("\u2019", "\u00e2\u20ac\u2122"),
        "field_keyword_05": "Italy",
        "field_keyword_08": "Consulting",
        "field_keyword_17": "Hybrid",
        "field_keyword_18": "Professional",
        "field_keyword_19": "Milan, IT",
        "field_keyword_20": "(1) IBM",
    }
    assert description(p) == "You\u2019ll lead\n• build\n• test"
    assert Ibm().tasks(SearchConfig())[0].board == HOST
