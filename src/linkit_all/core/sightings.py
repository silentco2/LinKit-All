"""Read helpers over `job_sightings` (repost history for the trust filter)."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from linkit_all.core.models import Job, JobSighting

_CHUNK = 500  # stay under SQLite's bound-variable limit


def first_seen(session: Session, job_id: int) -> datetime | None:
    """When the job was first returned by any source, or None if never recorded."""
    return session.scalar(select(func.min(JobSighting.seen_at)).where(JobSighting.job_id == job_id))


def seen_runs(session: Session, job_ids: Collection[int]) -> dict[int, int]:
    """Distinct runs each job was seen in; jobs without sightings are absent."""
    ids = list(job_ids)
    out: dict[int, int] = {}
    for i in range(0, len(ids), _CHUNK):
        rows = session.execute(
            select(JobSighting.job_id, func.count(distinct(JobSighting.run_id)))
            .where(JobSighting.job_id.in_(ids[i : i + _CHUNK]))
            .group_by(JobSighting.job_id)
        )
        out.update({j: n for j, n in rows})
    return out


@dataclass(frozen=True)
class SightingStats:
    first: datetime
    last: datetime
    runs: int
    urls: int


def sighting_stats(session: Session, job_ids: Collection[int]) -> dict[int, SightingStats]:
    """First/last sighting, distinct runs and distinct URLs per job, one query per 500 jobs."""
    ids = list(job_ids)
    out: dict[int, SightingStats] = {}
    for i in range(0, len(ids), _CHUNK):
        rows = session.execute(
            select(
                JobSighting.job_id,
                func.min(JobSighting.seen_at),
                func.max(JobSighting.seen_at),
                func.count(distinct(JobSighting.run_id)),
                func.count(distinct(JobSighting.url)),
            )
            .where(JobSighting.job_id.in_(ids[i : i + _CHUNK]))
            .group_by(JobSighting.job_id)
        )
        out.update({j: SightingStats(a, b, r, u) for j, a, b, r, u in rows})
    return out


def latest_run_id(session: Session) -> int | None:
    """Newest run that recorded any sighting."""
    return session.scalar(select(func.max(JobSighting.run_id)))


def company_run_counts(session: Session, companies: Collection[str]) -> dict[str, dict[int, int]]:
    """{company: {run_id: distinct jobs of that company seen in that run}}, exact company names;
    runs where the company had no sighting are absent."""
    names = list(companies)
    out: dict[str, dict[int, int]] = {}
    for i in range(0, len(names), _CHUNK):
        rows = session.execute(
            select(Job.company, JobSighting.run_id, func.count(distinct(JobSighting.job_id)))
            .join(Job, Job.id == JobSighting.job_id)
            .where(Job.company.in_(names[i : i + _CHUNK]), JobSighting.run_id.is_not(None))
            .group_by(Job.company, JobSighting.run_id)
        )
        for company, run_id, n in rows:
            if run_id is not None:
                out.setdefault(company, {})[run_id] = n
    return out
