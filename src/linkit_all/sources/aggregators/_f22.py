"""Helpers private to the F2.2 aggregator plugins (the underscore keeps it out of the registry)."""

from datetime import timedelta

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Task


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


def feed_task(name: str, cfg: SearchConfig) -> list[Task]:
    """One task that lists the newest postings; our own filters narrow them afterwards. The cap
    scales with the number of queries because one listing stands in for all of them."""
    s = cfg.search
    return [
        Task(name, f"{name}:feed", limit=s.max_results_per_query * max(1, len(s.queries)),
             posted_within_days=s.posted_within_days)
    ]  # fmt: skip


def all_older(stubs: list[JobStub], task: Task) -> bool:
    """True when every stub is dated before the task's window: a newest-first feed can stop."""
    cutoff = utcnow() - timedelta(days=task.posted_within_days)
    dated = [s.posted_at for s in stubs]
    return bool(dated) and all(d is not None and d < cutoff for d in dated)
