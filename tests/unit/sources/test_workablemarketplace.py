from collections.abc import Callable
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators.workablemarketplace import WorkableMarketplace
from linkit_all.sources.base import JobStub

FOREVER = 100_000  # the fixtures are dated; do not let their age filter them out


def paged_handler(
    load_fixture: Callable[[str], Any], seen: list[dict[str, str]] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path != "/api/v1/jobs":
            return httpx.Response(404)  # robots.txt
        if seen is not None:
            seen.append(dict(req.url.params))
        name = "page2" if req.url.params.get("pageToken") == "TOK2" else "page1"
        return httpx.Response(200, json=load_fixture(f"workablemarketplace/{name}.json"))

    return handler


def test_follows_the_page_token_and_maps_postings(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    sent: list[dict[str, str]] = []
    pages = search_pages(
        WorkableMarketplace(),
        paged_handler(load_fixture, sent),
        query="python developer",
        location="Athens",
        posted_within_days=FOREVER,
    )
    assert sent == [
        {"query": "python developer", "location": "Athens"},
        {"query": "python developer", "location": "Athens", "pageToken": "TOK2"},
    ]
    assert [len(p) for p in pages] == [2, 1]  # page 2's draft posting is dropped
    stafio, satori = pages[0]
    assert stafio.title == "Python Developer" and stafio.company == "Stafio.ai"
    assert stafio.url.startswith("https://jobs.workable.com/view/hW66kQAD12FZomzksq5y78/")
    assert stafio.location == "Noida, Uttar Pradesh, India" and stafio.remote == "onsite"
    assert stafio.description.index("Stafio.ai builds AI") < stafio.description.index(
        "Experience as"
    )
    assert stafio.posted_at is not None and stafio.posted_at.date().isoformat() == "2026-10-08"
    assert stafio.ats == "workable" and stafio.extra["id"] == "891f852f-c94e-4b49-a0d7-664b29eb0783"
    assert satori.remote == "hybrid" and "Perks on Perks." in satori.description
    assert pages[1][0].remote == "remote" and "x()" not in pages[1][0].description


def test_old_postings_are_filtered_and_resume_skips_yielded_pages(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    handler = paged_handler(load_fixture)
    assert search_pages(WorkableMarketplace(), handler, query="python", posted_within_days=1) == [
        [],
        [],
    ]
    resumed = search_pages(
        WorkableMarketplace(), handler, query="python", start_page=1, posted_within_days=FOREVER
    )
    assert [len(p) for p in resumed] == [1]


def test_stops_at_the_task_limit(
    search_pages: Callable[..., list[list[JobStub]]], load_fixture: Callable[[str], Any]
) -> None:
    sent: list[dict[str, str]] = []
    pages = search_pages(
        WorkableMarketplace(),
        paged_handler(load_fixture, sent),
        query="python",
        limit=2,
        posted_within_days=FOREVER,
    )
    assert len(sent) == 1 and [len(p) for p in pages] == [2]


def test_tasks_expand_queries_and_locations_and_need_opt_in() -> None:
    cfg = SearchConfig.model_validate(
        {"search": {"queries": ["python developer", "data engineer"], "locations": ["", "Egypt"]}}
    )
    src = WorkableMarketplace()
    tasks = src.tasks(cfg)
    assert len(tasks) == 4 and len({t.key for t in tasks}) == 4
    assert {(t.query, t.location) for t in tasks} >= {("python developer", "Egypt")}
    assert src.kind == "aggregator" and not src.is_enabled(cfg)
    cfg.sources.enabled = ["workablemarketplace"]
    assert src.is_enabled(cfg)
