"""Scheduled runs: APScheduler inside the FastAPI process, jobs kept in the app database.

The job store makes its own `apscheduler_jobs` table (created on start, not by Alembic, which
only runs explicit migrations). Jobs are plain cron entries that call `scheduled_run`; the app's
objects never get pickled, the runner is looked up in a module-level registry set at startup.
"""

from datetime import datetime, timedelta, tzinfo

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger
from sqlalchemy import Engine

from linkit_all.api.runner import PipelineRunner, RunBusy
from linkit_all.core.search import SearchConfig
from linkit_all.pipeline import STAGES

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
MISFIRE_GRACE_S = 3600  # a run missed while the app was closed still fires if it is < 1 h late

_runner: PipelineRunner | None = None


def register_runner(runner: PipelineRunner | None) -> None:
    global _runner
    _runner = runner


async def scheduled_run(new: bool) -> bool:
    """Cron target. Skips (never queues) when a run is already going. True if a run started."""
    if _runner is None:
        logger.warning("Scheduled run skipped: the app is not ready")
        return False
    try:
        _runner.start(list(STAGES), new=new)
    except RunBusy:
        logger.warning("Scheduled run skipped: a run is already in progress")
        return False
    logger.info("Scheduled run started")
    return True


def make_scheduler(
    engine: Engine | None = None, timezone: tzinfo | str | None = None
) -> AsyncIOScheduler:
    """Persistent when given the app DB engine, in memory otherwise (tests)."""
    store = (
        SQLAlchemyJobStore(engine=engine, tablename="apscheduler_jobs")
        if engine
        else MemoryJobStore()
    )
    return AsyncIOScheduler(
        jobstores={"default": store},
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": MISFIRE_GRACE_S},
        timezone=timezone,  # None = the machine's local zone
    )


def apply_schedule(sched: AsyncIOScheduler, cfg: SearchConfig) -> None:
    """Make the scheduler's jobs match cfg.schedule. Unchanged jobs are left alone, so a run
    missed while the app was closed (kept in the store) still fires after a restart."""
    s = cfg.schedule
    wanted: dict[str, CronTrigger] = {}
    if s.enabled:
        days = ",".join(DAY_NAMES[d] for d in s.days)
        for t in s.times:
            hour, minute = t.split(":")
            wanted[f"run-{hour}{minute}"] = CronTrigger(
                day_of_week=days, hour=int(hour), minute=int(minute), timezone=sched.timezone
            )
    current = {j.id: j for j in sched.get_jobs()}
    for job_id, job in list(current.items()):
        if (
            job_id not in wanted
            or str(job.trigger) != str(wanted[job_id])
            or job.args != (s.new_run,)
        ):
            sched.remove_job(job_id)
            current.pop(job_id)
    for job_id, trigger in wanted.items():
        if job_id not in current:
            sched.add_job(scheduled_run, trigger, args=[s.new_run], id=job_id)


def next_runs(sched: AsyncIOScheduler, n: int = 3) -> list[datetime]:
    """The next n fire times across all jobs, soonest first."""
    now = datetime.now(sched.timezone)
    times: list[datetime] = []
    for job in sched.get_jobs():
        prev: datetime | None = None
        for _ in range(n):
            prev = job.trigger.get_next_fire_time(
                prev, prev + timedelta(microseconds=1) if prev else now
            )
            if prev is None:
                break
            times.append(prev)
    return sorted(times)[:n]
