"""Read helpers over `job_sightings` (repost history for the trust filter).

Repost rule (`repost_listings`): logic adapted from career-ops (MIT).
"""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from linkit_all.core.models import Job, JobSighting

_CHUNK = 500  # stay under SQLite's bound-variable limit
REPOST_WINDOW_DAYS = 90


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
    urls: int  # listings that count for a repost: see `repost_listings`


def repost_listings(first_seen: Collection[date], window: int = REPOST_WINDOW_DAYS) -> int:
    """How many times a job was listed under a new URL, from the day each URL was first seen.

    A repost is the job coming back later under another URL. URLs first seen on the same day
    were open side by side (sibling requisitions with different ATS ids), so a day counts once;
    and only days within `window` of each other belong together. 1 = never reposted."""
    days = sorted(set(first_seen))
    span = timedelta(days=window)
    return max((sum(1 for d in days[i:] if d - start <= span) for i, start in enumerate(days)),
               default=0)  # fmt: skip


def sighting_stats(session: Session, job_ids: Collection[int]) -> dict[int, SightingStats]:
    """First/last sighting, distinct runs and repost listings per job, one query per 500 jobs.
    Rows are per (job, URL); a run sees a job once, so per-URL run counts add up exactly."""
    ids = list(job_ids)
    per_url: dict[int, list[tuple[datetime, datetime, int]]] = {}
    for i in range(0, len(ids), _CHUNK):
        for j, first, last, runs in session.execute(
            select(
                JobSighting.job_id,
                func.min(JobSighting.seen_at),
                func.max(JobSighting.seen_at),
                func.count(distinct(JobSighting.run_id)),
            )
            .where(JobSighting.job_id.in_(ids[i : i + _CHUNK]))
            .group_by(JobSighting.job_id, JobSighting.url)
        ):
            per_url.setdefault(j, []).append((first, last, runs))
    return {
        j: SightingStats(
            min(r[0] for r in rows),
            max(r[1] for r in rows),
            sum(r[2] for r in rows),
            repost_listings([r[0].date() for r in rows]),
        )
        for j, rows in per_url.items()
    }


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
