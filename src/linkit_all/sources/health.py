"""Source health (B2): did each switched-on source and each company page find jobs last time?

Two signals, one row per source (`SourceHealth`): every discover run records the jobs found and
any error per source; `check` runs a live one-page probe on demand (Settings > Sources "Check
now", `linkit source-check`), cached for an hour. Broken = an error with no jobs, or no jobs in
STREAK error-free runs in a row after the source had found jobs before. A source that never found
any is "empty", not broken. Marks only: runs still try every source (maintainer 2026-11-21)."""

import asyncio
import dataclasses
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import SourceHealth, utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import OPT_IN_KINDS, JobStub, Source, Task
from linkit_all.sources.http import Http

STREAK = 3
CACHE = timedelta(hours=1)
PROBE_TIMEOUT = 120.0  # seconds for one probe page; a jobspy site scrapes in a child process
PROBE_LIMIT = 5
PARALLEL = 4
COMPANY = "company:"
Status = Literal["ok", "warn", "broken", "empty"]


@dataclass
class Result:
    jobs: int = 0
    error: str | None = None


def key_of(task: Task, board_keys: set[str]) -> str | None:
    """The health row a discover task reports to; None for a stored (discovered) board, which
    keeps its own failure streak (`discovery.note_crawl`)."""
    if task.entry:
        return COMPANY + task.entry
    return None if task.key in board_keys else task.source


def wanted(cfg: SearchConfig, registry: Mapping[str, Source]) -> list[str]:
    """The keys to watch: switched-on sources and every entry of the company list."""
    on = [
        name
        for name, src in registry.items()
        if (name in cfg.sources.enabled if src.kind in OPT_IN_KINDS else bool(src.tasks(cfg)))
    ]
    return sorted(on) + [COMPANY + entry for entry in cfg.sources.companies]


def status(row: SourceHealth) -> Status:
    if row.error and not row.jobs:
        return "broken"
    if row.zero_streak >= STREAK and row.ever_found:
        return "broken"
    if row.error:
        return "warn"  # some searches failed, others found jobs
    return "ok" if row.jobs else "empty"


def record(
    db: sessionmaker[Session],
    results: Mapping[str, Result],
    via: Literal["run", "check"],
    now: datetime | None = None,
) -> None:
    now = now or utcnow()
    with db.begin() as s:
        for key, r in results.items():
            row = s.get(SourceHealth, key)
            if row is None:
                row = SourceHealth(key=key, zero_streak=0, ever_found=False)
                s.add(row)
            row.at, row.via, row.jobs, row.error = now, via, r.jobs, r.error
            if r.jobs:
                row.zero_streak, row.ever_found = 0, True
            elif r.error is None and via == "run":  # a probe asks for a handful only
                row.zero_streak += 1


def summary(
    db: sessionmaker[Session], keys: Iterable[str] | None = None
) -> dict[str, dict[str, object]]:
    """{key: {status, jobs, error, at, via}} for the stored rows (all, or just `keys`)."""
    with db() as s:
        query = select(SourceHealth)
        if keys is not None:
            query = query.where(SourceHealth.key.in_(list(keys)))
        rows = list(s.scalars(query))
    return {
        r.key: {"status": status(r), "jobs": r.jobs, "error": r.error, "via": r.via,
                "at": r.at.isoformat() + "Z", "zero_streak": r.zero_streak}
        for r in rows
    }  # fmt: skip


def _error(e: BaseException) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code}"
    if isinstance(e, TimeoutError):
        return f"no answer within {PROBE_TIMEOUT:.0f} s"
    return str(e) or type(e).__name__


async def _first_page(http: Http, src: Source, task: Task) -> Result:
    pages = src.search(http, dataclasses.replace(task, limit=PROBE_LIMIT), 0)
    try:
        stubs: list[JobStub] = await asyncio.wait_for(anext(pages, []), PROBE_TIMEOUT)
    except Exception as e:  # any failure is the answer: the source did not work
        return Result(error=_error(e))
    finally:
        await pages.aclose()  # type: ignore[attr-defined]
    return Result(jobs=len(stubs))


async def probe(http: Http, registry: dict[str, Source], cfg: SearchConfig, key: str) -> Result:
    """One live page of `key`'s first search (or its company page)."""
    from linkit_all.sources.runner import company_tasks  # late: the runner imports this module

    if key.startswith(COMPANY):
        one = cfg.model_copy(deep=True)
        one.sources.companies = [key.removeprefix(COMPANY)]
        tasks, unsupported = await company_tasks(one, http, registry)
        if not tasks:
            return Result(error=unsupported[0] if unsupported else "no job board found")
        return await _first_page(http, registry[tasks[0].source], tasks[0])
    src = registry.get(key)
    if src is None:
        return Result(error="no such source")
    tasks = src.tasks(cfg)
    if not tasks:
        return Result(error="nothing to search: add job titles (and places) in Settings")
    return await _first_page(http, src, tasks[0])


async def check(
    db: sessionmaker[Session],
    http: Http,
    registry: dict[str, Source],
    cfg: SearchConfig,
    keys: Iterable[str] | None = None,
    force: bool = False,
) -> dict[str, Result]:
    """Probe `keys` (default: everything `wanted`), skipping ones checked in the last hour unless
    `force`. The results are stored and returned."""
    keys = list(keys) if keys is not None else wanted(cfg, registry)
    fresh = utcnow() - CACHE
    with db() as s:
        recent = {
            r.key for r in s.scalars(select(SourceHealth).where(SourceHealth.key.in_(keys)))
            if r.via == "check" and r.at >= fresh
        }  # fmt: skip
    todo = [k for k in keys if force or k not in recent]
    gate = asyncio.Semaphore(PARALLEL)

    async def one(key: str) -> tuple[str, Result]:
        async with gate:
            return key, await probe(http, registry, cfg, key)

    results = dict(await asyncio.gather(*(one(k) for k in todo)))
    record(db, results, "check")
    return results
