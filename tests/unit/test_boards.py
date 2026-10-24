"""Discovered company boards: Common Crawl discovery, storage and crawl rotation (no live calls)."""

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from linkit_all.core.db import init_db
from linkit_all.core.models import Board, utcnow
from linkit_all.core.runs import current_run
from linkit_all.core.search import SearchConfig
from linkit_all.sources import registry
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.discovery import (
    DiscoveryError,
    board_tasks,
    discover_boards,
    make_http,
    slug_of,
    upsert_boards,
)
from linkit_all.sources.http import Http
from linkit_all.sources.runner import company_tasks, discover

INDEX = "https://index.commoncrawl.org/CC-MAIN-2026-43-index"
GH = "boards.greenhouse.io/*"
GH_URLS = [
    ["https://boards.greenhouse.io/stripe", "https://boards.greenhouse.io/stripe/jobs/1"],
    [
        "https://boards.greenhouse.io/Stripe/jobs/2",  # same board, other case
        "https://boards.greenhouse.io/embed/job_board?for=acme",
        "https://boards.greenhouse.io/robots.txt",
        "https://boards.greenhouse.io/figma",
    ],
]


async def no_sleep(_: float) -> None:
    return None


def cdx_handler(
    pages: dict[str, list[list[str]]], seen: list[httpx.Request] | None = None
) -> Callable[[httpx.Request], httpx.Response]:
    """Fake Common Crawl: `pages[pattern]` is a list of pages, each a list of URLs."""

    def handle(req: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(req)
        if req.url.path == "/robots.txt":
            return httpx.Response(404)
        if req.url.path == "/collinfo.json":
            return httpx.Response(200, json=[{"id": "CC-MAIN-2026-43"}, {"id": "CC-MAIN-2026-39"}])
        q = req.url.params
        assert str(req.url).startswith(INDEX) and q["output"] == "json" and q["fl"] == "url"
        assert q["filter"] == "status:200"
        data = pages.get(q["url"])
        if data is None:
            return httpx.Response(404, text="No Captures found")
        if "showNumPages" in q:
            return httpx.Response(200, json={"pages": len(data), "pageSize": 5})
        lines = [json.dumps({"url": u}) for u in data[int(q["page"])]]
        return httpx.Response(200, text="\n".join(lines) + "\n")

    return handle


def run(handler: Callable[[httpx.Request], httpx.Response], db: Any, **kw: Any) -> Any:
    async def go() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            http = Http(c, default_rate=1000, attempts=1)
            return await discover_boards(db, http, registry(), sleep=no_sleep, **kw)

    return asyncio.run(go())


def pages_asked(seen: list[httpx.Request]) -> list[str]:
    return [r.url.params["page"] for r in seen if "page" in r.url.params]


def stored(db: Any, ats: str) -> list[str]:
    with db() as s:
        return sorted(s.scalars(select(Board.slug).filter_by(ats=ats)))


def test_declared_hosts_cover_the_seven_ats() -> None:
    reg = registry()
    hosts = {n: reg[n].cdx_hosts for n in reg if reg[n].kind == "ats" and reg[n].cdx_hosts}
    assert set(hosts) >= {
        "greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee", "workday"
    }  # fmt: skip
    assert hosts["workday"] == ("*.myworkdayjobs.com",)


def test_slugs_use_the_plugins_own_patterns() -> None:
    reg = registry()
    assert slug_of("https://jobs.lever.co/palantir/abc", reg["lever"]) == "palantir"
    assert slug_of("https://jobs.lever.co/palantir", reg["greenhouse"]) is None
    assert slug_of("https://acme.recruitee.com/o/dev", reg["recruitee"]) == "acme"
    assert slug_of("https://www.recruitee.com/pricing", reg["recruitee"]) is None
    wd = reg["workday"]
    assert slug_of("https://nvidia.wd5.myworkdayjobs.com/en-US/Ext/job/x", wd) == "nvidia/wd5/Ext"
    assert slug_of("https://nvidia.wd5.myworkdayjobs.com/robots.txt", wd) is None
    assert slug_of("https://nvidia.wd5.myworkdayjobs.com/wday/authgwy/x", wd) is None


def test_paging_slugs_dedupe_and_upsert(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    seen: list[httpx.Request] = []
    h = cdx_handler({GH: GH_URLS}, seen)
    res = run(h, db, ats=["greenhouse"])
    assert res["greenhouse"].found == 3 and res["greenhouse"].new == 3
    assert stored(db, "greenhouse") == ["acme", "figma", "stripe"]  # first-seen case kept
    assert pages_asked(seen) == ["0", "1"]
    with db() as s:
        assert {b.source for b in s.scalars(select(Board))} == {"commoncrawl"}
    again = run(h, db, ats=["greenhouse"])  # idempotent
    assert again["greenhouse"].found == 3 and again["greenhouse"].new == 0
    assert len(stored(db, "greenhouse")) == 3


def test_cap_stops_paging(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    seen: list[httpx.Request] = []
    res = run(cdx_handler({GH: GH_URLS}, seen), db, ats=["greenhouse"], max_per_ats=1)
    assert res["greenhouse"].found == 1 and pages_asked(seen) == ["0"]
    seen.clear()
    res = run(cdx_handler({GH: GH_URLS}, seen), db, ats=["greenhouse"], max_per_ats=2)
    assert res["greenhouse"].found == 2 and pages_asked(seen) == ["0", "1"]


def test_all_ats_with_hosts_are_asked_and_empty_ones_reported(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    pages = {"jobs.lever.co/*": [["https://jobs.lever.co/palantir/x"]]}
    res = run(cdx_handler(pages), db)
    assert res["lever"].new == 1 and res["greenhouse"].found == 0
    assert {"workday", "ashby", "recruitee"} <= set(res)


def test_robots_refusal_and_bad_names(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    base = cdx_handler({GH: GH_URLS})

    def deny(req: httpx.Request) -> httpx.Response:
        if req.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /CC-\n")
        return base(req)

    with pytest.raises(DiscoveryError, match="robots"):
        run(deny, db, ats=["greenhouse"])
    with pytest.raises(ValueError, match="nope"):
        run(base, db, ats=["nope"])
    assert stored(db, "greenhouse") == []


def test_failure_midway_keeps_what_was_found(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    base = cdx_handler({GH: GH_URLS})

    def flaky(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503) if req.url.params.get("page") == "1" else base(req)

    res = run(flaky, db, ats=["greenhouse"])
    assert res["greenhouse"].found == 1 and not res["greenhouse"].error
    assert stored(db, "greenhouse") == ["stripe"]


def test_total_failure_is_reported_per_ats(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    base = cdx_handler({GH: GH_URLS})

    def down(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503) if "url" in req.url.params else base(req)

    res = run(down, db, ats=["greenhouse"])
    assert res["greenhouse"].error and res["greenhouse"].found == 0


def test_make_http_throttles_the_index() -> None:
    async def go() -> float:
        async with httpx.AsyncClient() as c:
            return make_http(c)._rates["index.commoncrawl.org"]

    assert asyncio.run(go()) == 1.0


def test_table_defaults_unique_and_case_insensitive_upsert(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")  # runs the migrations
    assert upsert_boards(db, "lever", ["a", "A", "b"], "user") == 2
    with db() as s:
        b = s.scalars(select(Board).filter_by(slug="a")).one()
        assert b.active and b.failures == 0 and b.last_jobs == 0 and b.last_crawled_at is None
    with pytest.raises(IntegrityError), db.begin() as s:
        s.add_all(
            [Board(ats="x", slug="s", source="user"), Board(ats="x", slug="s", source="user")]
        )


# --- crawling in rotation -------------------------------------------------------------------


class FakeAts(Source):
    kind = "ats"
    parallel = 4

    def __init__(self, name: str = "greenhouse", fail: tuple[str, ...] = ()) -> None:
        self.name, self.fail = name, fail
        self.crawled: list[str] = []

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        self.crawled.append(task.board)
        if task.board in self.fail:
            raise RuntimeError("boom")
        yield [
            JobStub(
                source=self.name, url=f"https://x.io/{task.board}/{i}", title=f"T{i}",
                company=f"Co {task.board}", description="d", ats=self.name,
            )
            for i in range(2)
        ]  # fmt: skip


def run_discover(db: Any, cfg: SearchConfig, src: FakeAts) -> Any:
    async def go() -> Any:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(404))
        ) as c:
            http = Http(c, default_rate=1000, attempts=1)
            return await discover(db, cfg, current_run(db, True), http, {src.name: src})

    return asyncio.run(go())


def seeded(tmp_path: Path) -> Any:
    db = init_db(tmp_path / "t.db")
    upsert_boards(db, "greenhouse", ["a", "b", "c", "d"], "commoncrawl")
    now = utcnow()
    with db.begin() as s:
        for slug, days in {"a": 5, "c": 9, "d": 7}.items():  # b never crawled
            board = s.scalars(select(Board).filter_by(slug=slug)).one()
            board.last_crawled_at = now - timedelta(days=days)
    return db


def cfg_with(**sources: Any) -> SearchConfig:
    return SearchConfig.model_validate({"sources": sources})


def row(db: Any, slug: str) -> Board:
    with db() as s:
        return s.scalars(select(Board).filter_by(slug=slug)).one()


def test_rotation_takes_never_crawled_then_oldest_and_updates_stats(tmp_path: Path) -> None:
    db = seeded(tmp_path)
    src = FakeAts()
    before = utcnow()
    run_discover(db, cfg_with(use_discovered_boards=True, boards_per_run=2), src)
    assert sorted(src.crawled) == ["b", "c"]
    for slug in "bc":
        b = row(db, slug)
        assert b.last_crawled_at and b.last_crawled_at >= before
        assert b.last_jobs == 2 and b.failures == 0
    assert row(db, "a").last_jobs == 0
    src2 = FakeAts()  # the next run moves on to the next-oldest
    run_discover(db, cfg_with(use_discovered_boards=True, boards_per_run=2), src2)
    assert sorted(src2.crawled) == ["a", "d"]


def test_off_by_default_and_zero_budget(tmp_path: Path) -> None:
    db = seeded(tmp_path)
    for cfg in (SearchConfig(), cfg_with(use_discovered_boards=True, boards_per_run=0)):
        src = FakeAts()
        run_discover(db, cfg, src)
        assert src.crawled == []


def test_user_companies_always_run_and_are_not_counted_or_rotated(tmp_path: Path) -> None:
    db = seeded(tmp_path)
    src = FakeAts()
    cfg = cfg_with(
        companies=["greenhouse:c", "greenhouse:mine"], use_discovered_boards=True, boards_per_run=2
    )
    run_discover(db, cfg, src)
    # c and mine come from the list; the budget of 2 goes to b (never crawled) and d (c is skipped)
    assert sorted(src.crawled) == ["b", "c", "d", "mine"]
    assert row(db, "c").last_crawled_at < utcnow() - timedelta(
        days=8
    )  # user board: stats untouched
    assert row(db, "mine").source == "user"
    src2 = FakeAts()  # the user's list runs even with the feature off
    run_discover(db, cfg_with(companies=["greenhouse:mine"]), src2)
    assert src2.crawled == ["mine"]


def test_five_failures_in_a_row_deactivate(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    upsert_boards(db, "greenhouse", ["bad", "good"], "commoncrawl")
    cfg = cfg_with(use_discovered_boards=True, boards_per_run=10)
    for n in range(1, 5):
        run_discover(db, cfg, FakeAts(fail=("bad",)))
        assert row(db, "bad").failures == n and row(db, "bad").active
    run_discover(db, cfg, FakeAts())  # a success resets the streak
    assert row(db, "bad").failures == 0
    for _ in range(5):
        run_discover(db, cfg, FakeAts(fail=("bad",)))
    bad = row(db, "bad")
    assert bad.failures == 5 and not bad.active
    assert row(db, "good").active and row(db, "good").failures == 0
    src = FakeAts(fail=("bad",))
    run_discover(db, cfg, src)
    assert src.crawled == ["good"]  # the switched-off board is no longer asked


def test_board_tasks_ignore_unregistered_ats(tmp_path: Path) -> None:
    db = seeded(tmp_path)
    upsert_boards(db, "lever", ["z"], "commoncrawl")
    tasks = board_tasks(db, cfg_with(use_discovered_boards=True), {"greenhouse": FakeAts()}, set())
    assert {t.source for t in tasks} == {"greenhouse"} and len(tasks) == 4


def test_company_tasks_store_user_and_detected_boards(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    html = '<a href="https://boards.greenhouse.io/zeta">jobs</a>'

    def handle(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html) if req.url.path == "/careers" else httpx.Response(404)

    cfg = cfg_with(companies=["greenhouse:acme", "https://zeta.test/careers"])

    async def go() -> list[Task]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as c:
            http = Http(c, default_rate=1000, attempts=1)
            tasks, _ = await company_tasks(cfg, http, {"greenhouse": FakeAts()}, db)
            return tasks

    assert [t.key for t in asyncio.run(go())] == ["greenhouse:acme", "greenhouse:zeta"]
    assert row(db, "acme").source == "user" and row(db, "zeta").source == "detected"
