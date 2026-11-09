"""Pipeline runs: stages attach to the latest unfinished run so crashes resume."""

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Run, RunStatus, utcnow

RESUMABLE = (RunStatus.running, RunStatus.paused, RunStatus.cancelled)


def current_run(db: sessionmaker[Session], new: bool = False) -> int:
    """The newest run if it can go on (a cancelled one too: its page checkpoints are kept), else a
    new run. `new` discards an unfinished run: it stays in the history but never resumes."""
    with db.begin() as s:
        if new:
            s.execute(
                update(Run)
                .where(Run.status.in_([RunStatus.running, RunStatus.paused]))
                .values(status=RunStatus.cancelled, finished_at=utcnow())
            )
        else:
            run = s.scalars(select(Run).order_by(Run.id.desc())).first()
            if run is not None and run.status in RESUMABLE:
                run.status, run.finished_at = RunStatus.running, None
                run.pause_reason, run.reason_code, run.reason_params = None, None, {}
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


def add_stage(db: sessionmaker[Session], run_id: int, stage: str) -> None:
    with db.begin() as s:
        run = s.get_one(Run, run_id)
        if stage not in run.stages:
            run.stages = [*run.stages, stage]


def skip_unfinished(db: sessionmaker[Session], run_id: int, before: str) -> None:
    """Stages of this run ahead of `before` that never finished count as done: the run goes on
    with what they stored."""
    with db.begin() as s:
        run = s.get_one(Run, run_id)
        earlier = run.stages[: run.stages.index(before)]
        run.stats = {**{k: {"stopped_early": True} for k in earlier}, **run.stats}


def pause_run(
    db: sessionmaker[Session], run_id: int, message: str, code: str, params: dict[str, Any]
) -> None:
    """Stop the run cleanly (AI usage limit, LibreOffice missing): resuming continues it."""
    with db.begin() as s:
        run = s.get_one(Run, run_id)
        run.status, run.pause_reason = RunStatus.paused, message
        run.reason_code, run.reason_params = code, params


def note_failure(
    db: sessionmaker[Session], run_id: int, message: str, code: str, params: dict[str, Any]
) -> None:
    """Remember why a stage failed. The status stays: the run is resumable, as before."""
    with db.begin() as s:
        run = s.get_one(Run, run_id)
        run.pause_reason, run.reason_code, run.reason_params = message, code, params


def pause_of(db: sessionmaker[Session], run_id: int) -> tuple[str, str, dict[str, Any]] | None:
    """(message, code, params) when a stage paused this run, else None."""
    with db() as s:
        run = s.get_one(Run, run_id)
        if run.status != RunStatus.paused:
            return None
        return run.pause_reason or "", run.reason_code or "", dict(run.reason_params)


def run_kind(run: Run) -> str:
    """ "apply" (only the apply stage), "mixed" (apply plus any search stage) or "search"
    (everything else: discover, enrich, rank, score). Old runs without `stages` use their stats."""
    stages = set(run.stages or run.stats)
    if "apply" not in stages:
        return "search"
    return "apply" if stages == {"apply"} else "mixed"
