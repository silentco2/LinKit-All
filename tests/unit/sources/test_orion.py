from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.orion import Orion


def test_feed(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    pages = search_pages(
        Orion(), lambda req: httpx.Response(200, json=load_fixture("orion/list.json"))
    )
    assert len(pages) == 1 and len(pages[0]) == 3  # pagination.to reached total: no second page
    job = pages[0][0]
    assert job.title == "Project Manager I" and job.company == "Orion Group"
    assert job.url == "https://www.orionjobs.com/job/project-manager-i/"
    assert job.location == "United States, Illinois, Lake Bluff" and job.remote is None
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-10-23T00:00:00"
    assert "Associate Project Planner" in job.description and "<" not in job.description
    assert job.extra["employment_type"] == "Contract"
    assert pages[0][2].remote == "remote"  # "United States, Remote work"


def test_paging(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        data = load_fixture("orion/list.json")
        if req.url.params["page"] == "1":
            data["items"], data["pagination"]["to"], data["pagination"]["total"] = (
                data["items"][:2],
                2,
                3,
            )
        elif req.url.params["page"] == "2":
            data["items"], data["pagination"]["to"], data["pagination"]["total"] = (
                data["items"][2:],
                3,
                3,
            )
        else:
            data["items"] = []
        return httpx.Response(200, json=data)

    assert [len(p) for p in search_pages(Orion(), handler)] == [2, 1]
    assert [len(p) for p in search_pages(Orion(), handler, start_page=1)] == [1]
