from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.lumenalta import HOST, Lumenalta


def test_search_maps_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    pages = search_pages(
        Lumenalta(),
        lambda req: httpx.Response(200, json=load_fixture("lumenalta/jobs.json")),
        board=HOST,
        calls=calls,
    )
    assert calls == [f"https://{HOST}/api/jobs?page=1&limit=100"]
    assert len(pages) == 1 and len(pages[0]) == 1  # the posting without a slug is left out
    job = pages[0][0]
    assert job.title == "Senior AI Engineer" and job.company == "Lumenalta"
    assert job.url == f"https://{HOST}/careers/ai-engineer-ai-engineer-551"
    assert job.location == "Remote" and job.remote == "remote" and job.ats == "lumenalta"
    assert job.description.startswith("At Lumenalta") and "- Ship code" in job.description
    assert job.extra == {"id": "68dee35f8c9481db144ea376"}


def test_pages_until_total_and_resume(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        page = int(req.url.params["page"])
        seen.append(str(page))
        n = 100 if page == 1 else 5
        jobs = [{"_id": f"{page}-{i}", "slug": f"s{page}-{i}", "name": "J"} for i in range(n)]
        return httpx.Response(200, json={"data": jobs, "meta": {"total": 105}})

    pages = search_pages(Lumenalta(), handler, board=HOST)
    assert seen == ["1", "2"] and [len(p) for p in pages] == [100, 5]
    seen.clear()
    search_pages(Lumenalta(), handler, board=HOST, start_page=1)
    assert seen == ["2"]


def test_empty_feed_and_task() -> None:
    assert Lumenalta().tasks(SearchConfig())[0].board == HOST
    assert Lumenalta().kind == "company" and not Lumenalta().is_enabled(SearchConfig())
