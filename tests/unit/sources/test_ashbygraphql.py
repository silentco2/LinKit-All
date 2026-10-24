import json
from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.ats.ashbygraphql import AshbyGraphQL
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub


def test_list_query_then_a_detail_query_per_posting(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    bodies: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method != "POST":
            return httpx.Response(404)  # robots.txt
        body = json.loads(req.content)
        bodies.append(body)
        if body["operationName"] == "ApiJobBoardWithTeams":
            return httpx.Response(200, json=load_fixture("ashbygraphql/list.json"))
        if body["variables"]["jobPostingId"] == "961b9946":
            return httpx.Response(200, json=load_fixture("ashbygraphql/detail.json"))
        return httpx.Response(500)  # the other posting's detail query keeps failing

    pages = search_pages(AshbyGraphQL(), handler, board="chainlink-labs")
    assert bodies[0]["variables"] == {"organizationHostedJobsPageName": "chainlink-labs"}
    assert {b["operationName"] for b in bodies} == {"ApiJobBoardWithTeams", "ApiJobPosting"}
    assert len(pages) == 1 and len(pages[0]) == 1  # the failed detail drops only that posting
    job = pages[0][0]
    assert job.title == "Blockchain Security Analyst" and job.company == "Chainlink Labs"
    assert job.url == "https://jobs.ashbyhq.com/chainlink-labs/961b9946"
    assert job.location == "Remote - US" and job.remote == "remote"
    assert "About Chainlink" in job.description and "Audit contracts" in job.description
    assert job.source == "ashbygraphql" and job.ats == "ashby"  # applied through Ashby's handler
    assert job.extra == {"board": "chainlink-labs", "id": "961b9946", "employment": "FullTime"}


def test_unknown_board_is_empty_and_resume(
    search_pages: Callable[..., list[list[JobStub]]],
) -> None:
    nothing = lambda req: httpx.Response(200, json={"data": {"jobBoard": None}})  # noqa: E731
    assert search_pages(AshbyGraphQL(), nothing, board="nope") == []
    assert search_pages(AshbyGraphQL(), nothing, board="nope", start_page=1) == []


def test_board_is_named_not_detected() -> None:
    assert detect("ashbygraphql:toggl") == ("ashbygraphql", "toggl")
    assert detect("https://jobs.ashbyhq.com/toggl") == ("ashby", "toggl")  # stays with ashby.py
