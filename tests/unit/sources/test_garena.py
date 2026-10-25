import json
from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.garena import HOST, Garena


def test_list_is_one_post(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    seen: list[tuple[str, str, bytes]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, str(req.url), req.content))
        return httpx.Response(200, json=load_fixture("garena/garena_list.json"))

    pages = search_pages(Garena(), handler, board=HOST)
    assert seen == [("POST", f"https://{HOST}/api/job/list?office=global", b"{}")]
    assert len(pages) == 1 and len(pages[0]) == 4
    mode = next(s for s in pages[0] if s.title.startswith("Game Mode Developer"))
    assert mode.company == "Garena" and mode.location == "Jakarta" and mode.remote is None
    assert mode.url == f"https://{HOST}/global/careers/J02058270"
    assert mode.extra["id"] == "J02058270" and mode.extra["type"] == ["Internship"]
    scout = next(s for s in pages[0] if s.extra["id"] == "J02187012")
    assert scout.remote == "remote" and scout.location == ""  # the only tag is "Remote"
    assert search_pages(Garena(), handler, board=HOST, start_page=1) == []


def test_listing_without_jobs_array_fails(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    try:
        search_pages(Garena(), lambda req: httpx.Response(200, json={"filters": {}}), board=HOST)
    except ValueError as e:
        assert "no jobs array" in str(e)
    else:
        raise AssertionError("an empty listing must not read as an empty catalogue")


def test_details_assemble_the_page_body(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    stub = JobStub(
        source="garena", url=f"https://{HOST}/global/careers/J02187012", title="x", company="Garena"
    )
    full = fetch_details(
        Garena(),
        lambda req: httpx.Response(200, json=load_fixture("garena/garena_detail_J02187012.json")),
        stub,
    )
    assert "Job Description" in full.description and "Job Requirements" in full.description
    assert "Identify global gaming investment" in full.description
    assert "Bachelor's degree" in full.description  # entity decoded
    assert full.description.index("Job Description") < full.description.index("Job Requirements")


def test_gone_posting_keeps_the_stub(fetch_details: Callable[..., JobStub]) -> None:
    stub = JobStub(source="garena", url=f"https://{HOST}/global/careers/J1", title="x", company="G")
    gone = fetch_details(Garena(), lambda req: httpx.Response(200, content=b'{"job": {}}'), stub)
    assert gone.description == ""
    assert json.loads('{"job": {}}') == {"job": {}}
    assert Garena().tasks(SearchConfig())[0].board == HOST
