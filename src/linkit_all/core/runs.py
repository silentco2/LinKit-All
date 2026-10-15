"""Pipeline runs: stages attach to the latest unfinished run so crashes resume."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Run, RunStatus


def current_run(db: sessionmaker[Session], new: bool = False) -> int:
    with db.begin() as s:
        if not new:
            run = s.scalars(
                select(Run)
                .where(Run.status.in_([RunStatus.running, RunStatus.paused]))
                .order_by(Run.id.desc())
            ).first()
            if run is not None:
                run.status = RunStatus.running
                return run.id
        run = Run()
        s.add(run)
        s.flush()
        return run.id


def record_stats(db: sessionmaker[Session], run_id: int, stage: str, stats: Any) -> None:
    with db.begin() as s:
        run = s.get_one(Run, run_id)
        run.stats = {**run.stats, stage: stats}  # new dict so the JSON change is saved
