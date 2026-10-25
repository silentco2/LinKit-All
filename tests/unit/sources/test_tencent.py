from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub
from linkit_all.sources.companies.tencent import PAGE, Tencent, posted


def test_search_keeps_native_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    calls: list[str] = []
    data = load_fixture("tencent/query.json")
    pages = search_pages(
        Tencent(), lambda req: httpx.Response(200, json=data), query="python", calls=calls
    )
    assert "parentCategoryId=40001" in calls[0] and "keyword=python" in calls[0]
    assert "pageIndex=1" in calls[0] and "language=en-us" in calls[0]
    assert len(calls) == 1 and len(pages) == 1
    stubs = pages[0]
    assert len(stubs) == 4  # the two re-listed Workday postings (SourceID 4) are left out
    job = stubs[0]
    assert job.url == "https://careers.tencent.com/jobdesc.html?postId=2071854045013913600"
    assert job.company == "Tencent" and job.location == "Shenzhen, China" and job.ats == "tencent"
    assert job.title.startswith("混元后台开发工程师")
    assert job.posted_at is not None and job.posted_at.isoformat() == "2026-10-15T00:00:00"
    assert job.extra["id"] == "2071854045013913600"


def test_pages_until_count(search_pages: Callable[..., list[list[JobStub]]]) -> None:
    seen: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        index = int(req.url.params["pageIndex"])
        seen.append(str(index))
        n = PAGE if index == 1 else 3
        posts = [
            {"PostId": str(index * 1000 + i), "RecruitPostName": f"J{i}", "SourceID": 1}
            for i in range(n)
        ]
        return httpx.Response(200, json={"Code": 200, "Data": {"Count": PAGE + 3, "Posts": posts}})

    pages = search_pages(Tencent(), handler, limit=1000)
    assert seen == ["1", "2"] and [len(p) for p in pages] == [PAGE, 3]
    seen.clear()
    search_pages(Tencent(), handler, start_page=1, limit=1000)
    assert seen == ["2"]
    # The task limit cuts the run off after that many postings.
    assert sum(len(p) for p in search_pages(Tencent(), handler, limit=10)) == 10


def test_fetch_details_joins_the_sections(
    fetch_details: Callable[..., JobStub], load_fixture: Callable[[str], Any]
) -> None:
    data = load_fixture("tencent/post_2008500879786921984.json")
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(200, json=data)

    stub = JobStub(
        source="tencent",
        url="https://careers.tencent.com/jobdesc.html?postId=2008500879786921984",
        title="t",
        company="Tencent",
    )
    out = fetch_details(Tencent(), handler, stub)
    assert "postId=2008500879786921984" in calls[0] and "/ByPostId" in calls[0]
    assert out.description.startswith("在腾讯") and "\r" not in out.description
    assert "负责腾讯安全相关产品" in out.description and "linux经验者优先" in out.description
    other = {"Code": 200, "Data": {"PostId": "1"}}  # a different posting: leave the stub alone
    same = fetch_details(Tencent(), lambda req: httpx.Response(200, json=other), stub)
    assert same.description == ""


def test_date_and_tasks() -> None:
    assert posted("October 15,2026") is not None and posted("nonsense") is None
    cfg = SearchConfig.model_validate({"search": {"queries": ["go", "rust"]}})
    assert [t.query for t in Tencent().tasks(cfg)] == ["go", "rust"]
    assert [t.query for t in Tencent().tasks(SearchConfig())] == [""]
