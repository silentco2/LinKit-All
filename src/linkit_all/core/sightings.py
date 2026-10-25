"""Read helpers over `job_sightings` (repost history for the trust filter)."""

from collections.abc import Collection
from datetime import datetime

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from linkit_all.core.models import JobSighting

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
