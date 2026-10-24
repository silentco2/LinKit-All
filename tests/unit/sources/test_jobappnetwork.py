import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from linkit_all.sources.ats import jobappnetwork
from linkit_all.sources.ats.jobappnetwork import JobAppNetwork
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def _serve(
    load_fixture: Callable[[str], Any], bodies: list[dict[str, Any]] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    hits = load_fixture("jobappnetwork/page1.json")["hits"]["hits"]

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        body = json.loads(req.content)
        if bodies is not None:
            bodies.append(body)
        window = hits[body["from"] : body["from"] + body["size"]]
        return httpx.Response(200, json={"hits": {"total": len(hits), "hits": window}})

    return handler


def test_search_maps_the_posting_and_filters_the_query(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    bodies: list[dict[str, Any]] = []
    pages = search_pages(JobAppNetwork(), _serve(load_fixture, bodies), board="20448")
    assert len(pages) == 1 and len(bodies) == 1
    assert bodies[0]["query"]["bool"]["filter"] == [
        {"term": {"clientId": 20448}},
        {"term": {"internalOrExternal": "externalOnly"}},
    ]
    job = pages[0][0]
    assert job.title == "Shift Leader" and job.location == "Houston, TX, US"
    assert job.url == "https://apply.jobappnetwork.com/clients/20448/posting/7216553/"
    assert job.description == "Lead the shift."
    assert job.posted_at is not None and job.posted_at.isoformat() == "2022-02-16T00:00:00"
    assert job.extra == {"board": "20448", "id": "7216553"} and job.ats == "jobappnetwork"
    assert job.company == "Client 20448"


def test_paging_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
    load_fixture: Callable[[str], Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobappnetwork, "PAGE_SIZE", 1)
    bodies: list[dict[str, Any]] = []
    pages = search_pages(JobAppNetwork(), _serve(load_fixture, bodies), board="20448")
    assert [p[0].extra["id"] for p in pages] == ["7216553", "7216554"]
    assert [b["from"] for b in bodies] == [0, 1]
    bodies.clear()
    pages = search_pages(JobAppNetwork(), _serve(load_fixture, bodies), board="20448", start_page=1)
    assert [p[0].extra["id"] for p in pages] == ["7216554"] and [b["from"] for b in bodies] == [1]


def test_a_board_must_be_a_client_id(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    with pytest.raises(ValueError, match="numeric client id"):
        search_pages(JobAppNetwork(), lambda req: httpx.Response(200, json={}), board="acme")


def test_total_may_be_an_object(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    hit = {"_source": {"jobId": 1, "title": "T", "address": {}}}

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hits": {"total": {"value": 1}, "hits": [hit]}})

    pages = search_pages(JobAppNetwork(), handler, board="7")
    assert len(pages) == 1 and pages[0][0].url.endswith("/clients/7/posting/1/")


def test_url_patterns() -> None:
    url = "https://apply.jobappnetwork.com/clients/20448/posting/7216553/"
    assert detect(url) == ("jobappnetwork", "20448")
    assert detect("jobappnetwork:20448") == ("jobappnetwork", "20448")
