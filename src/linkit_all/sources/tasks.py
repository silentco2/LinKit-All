"""Task builders and result filters shared by aggregator, board and company plugins."""

from collections.abc import AsyncIterator, Iterable
from datetime import timedelta
from typing import TypeVar

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Task

T = TypeVar("T")


def query_tasks(name: str, cfg: SearchConfig, *, locations: bool = True) -> list[Task]:
    """One task per query (x location when the API filters by place); none without queries."""
    s = cfg.search
    places = s.locations if locations else [""]
    return [
        Task(name, f"{name}:{q}@{loc}", query=q, location=loc,
             limit=s.max_results_per_query, posted_within_days=s.posted_within_days)
        for q in s.queries
        for loc in places
    ]  # fmt: skip


def company_query_tasks(name: str, cfg: SearchConfig) -> list[Task]:
    """One task per search query, for a company API that searches; one unfiltered task (the
    newest postings) when no query is set."""
    s = cfg.search
    return [
        Task(name, f"{name}:{q}", query=q, limit=s.max_results_per_query,
             posted_within_days=s.posted_within_days)
        for q in s.queries or [""]
    ]  # fmt: skip


def feed_task(name: str, cfg: SearchConfig) -> list[Task]:
    """One task that lists the newest postings; our own filters narrow them afterwards. The cap
    scales with the number of queries because one listing stands in for all of them."""
    s = cfg.search
    return [
        Task(name, f"{name}:feed", limit=s.max_results_per_query * max(1, len(s.queries)),
             posted_within_days=s.posted_within_days)
    ]  # fmt: skip


def careers_task(name: str) -> list[Task]:
    """The single task of a company whose careers page is the whole source."""
    return [Task(name, f"{name}:careers")]


def all_older(stubs: list[JobStub], task: Task) -> bool:
    """True when every stub is dated before the task's window: a newest-first feed can stop."""
    cutoff = utcnow() - timedelta(days=task.posted_within_days)
    dated = [s.posted_at for s in stubs]
    return bool(dated) and all(d is not None and d < cutoff for d in dated)


async def limited(pages: AsyncIterator[list[T]], limit: int) -> AsyncIterator[list[T]]:
    """`pages` cut off after `limit` items in all."""
    left = limit
    async for page in pages:
        if left <= 0:
            return
        yield page[:left]
        left -= len(page)


def fresh(stubs: Iterable[JobStub | None], seen: set[str]) -> list[JobStub]:
    """The stubs whose `extra["id"]` is not yet in `seen` (added to it), in order; skips None."""
    out: list[JobStub] = []
    for s in stubs:
        if s and s.extra["id"] not in seen:
            seen.add(s.extra["id"])
            out.append(s)
    return out
