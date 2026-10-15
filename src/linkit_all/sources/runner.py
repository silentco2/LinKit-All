"""Discover and enrich stages."""

import asyncio
from dataclasses import dataclass, field

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Job, JobState, SourceCheckpoint
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.store import Deduper, mark_task, store_page


@dataclass
class DiscoverStats:
    new: int = 0
    duplicates: int = 0
    tasks_done: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    unsupported: list[str] = field(default_factory=list)


async def company_tasks(
    cfg: SearchConfig, http: Http, registry: dict[str, Source]
) -> tuple[list[Task], list[str]]:
    """Resolve the company list (URLs or shorthands) to ATS board tasks."""
    tasks: dict[str, Task] = {}
    unsupported = []
    for entry in cfg.sources.companies:
        found = detect(entry)
        if found is None and entry.startswith("http"):
            try:  # a company's own careers page usually embeds its ATS
                resp = await http.get(entry)
                found = detect(resp.text) if resp.status_code < 400 else None
            except httpx.HTTPError:
                found = None
        if found is None:
            unsupported.append(f"{entry} (no known ATS found)")
        elif found[0] not in registry:
            unsupported.append(f"{entry} ({found[0]} not supported yet)")
        else:
            ats, board = found
            tasks.setdefault(f"{ats}:{board}", Task(ats, f"{ats}:{board}", board=board))
    return list(tasks.values()), unsupported


async def discover(
    db: sessionmaker[Session],
    cfg: SearchConfig,
    run_id: int,
    http: Http,
    registry: dict[str, Source],
    concurrency: int = 4,
) -> DiscoverStats:
    stats = DiscoverStats()
    tasks, stats.unsupported = await company_tasks(cfg, http, registry)
    tasks += [t for src in registry.values() for t in src.tasks(cfg)]
    with db() as s:
        deduper = Deduper(s)
        checkpoints = {
            c.key: (c.next_page, c.done)
            for c in s.scalars(select(SourceCheckpoint).filter_by(run_id=run_id))
        }
    sem = asyncio.Semaphore(concurrency)

    async def run(task: Task) -> None:
        start, done = checkpoints.get(task.key, (0, False))
        if done:
            return
        async with sem:
            page = start
            try:
                async for stubs in registry[task.source].search(http, task, start):
                    new = store_page(db, run_id, task.key, page, stubs, deduper)
                    stats.new += new
                    stats.duplicates += len(stubs) - new
                    logger.info("{} page {}: {} new of {}", task.key, page, new, len(stubs))
                    page += 1
            except httpx.HTTPStatusError as e:  # e.g. board removed: retrying will not help
                stats.errors[task.key] = str(e)
                mark_task(db, run_id, task.key, str(e))
            except Exception as e:  # network, parsing: leave undone so a resume retries
                stats.errors[task.key] = f"{type(e).__name__}: {e}"
                logger.warning("{} failed: {}", task.key, stats.errors[task.key])
            else:
                stats.tasks_done += 1
                mark_task(db, run_id, task.key, None)

    # Higher-priority sources (company ATS APIs) first, so their copy of a duplicate wins.
    for priority in sorted({registry[t.source].priority for t in tasks}):
        await asyncio.gather(*(run(t) for t in tasks if registry[t.source].priority == priority))
    return stats


async def enrich(db: sessionmaker[Session], http: Http, registry: dict[str, Source]) -> int:
    """discovered -> enriched, fetching descriptions the listing did not include."""
    with db.begin() as s:
        jobs = list(s.scalars(select(Job).filter_by(state=JobState.discovered)))
        for job in jobs:
            if job.description:
                transition(s, job, JobState.enriched)
        missing = [
            JobStub(
                source=j.source, url=j.url, title=j.title, company=j.company, extra={"id": j.id}
            )
            for j in jobs
            if not j.description and j.source in registry
        ]
    enriched = len(jobs) - len(missing)
    for stub in missing:
        try:
            description = (await registry[stub.source].fetch_details(http, stub)).description
        except Exception as e:  # leave it discovered; the next enrich run retries
            logger.warning("details for job {} failed: {}", stub.extra["id"], e)
            continue
        if description:
            with db.begin() as s:
                row = s.get_one(Job, stub.extra["id"])
                row.description = description
                transition(s, row, JobState.enriched)
            enriched += 1
    return enriched
