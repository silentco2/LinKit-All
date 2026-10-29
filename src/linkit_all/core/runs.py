"""Pipeline runs: stages attach to the latest unfinished run so crashes resume."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Run, RunStatus, utcnow


def current_run(db: sessionmaker[Session], new: bool = False) -> int:
    with db.begin() as s:
        if not new:
            run = s.scalars(
                select(Run)
                .where(Run.status.in_([RunStatus.running, RunStatus.paused, RunStatus.cancelled]))
                .order_by(Run.id.desc())
            ).first()
            if run is not None:  # a cancelled run resumes too: its page checkpoints are kept
                run.status, run.finished_at = RunStatus.running, None
                return run.id
        run = Run()
        s.add(run)
        s.flush()
        return run.id


def cancel_run(db: sessionmaker[Session], run_id: int) -> None:
    """The worker has stopped: end the run row (the next start resumes it)."""
    with db.begin() as s:
        run = s.get_one(Run, run_id)
        if run.status == RunStatus.running:
            run.status, run.finished_at = RunStatus.cancelled, utcnow()


def record_stats(db: sessionmaker[Session], run_id: int, stage: str, stats: Any) -> None:
    with db.begin() as s:
        run = s.get_one(Run, run_id)
        run.stats = {**run.stats, stage: stats}  # new dict so the JSON change is saved
