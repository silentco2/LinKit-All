"""Apply test across sources: one job per source, run in Practice mode, one report.

Shows where each kind of application gets to (filled and ready to submit, parked and why, or
failed) without submitting anything. Jobs you had not chosen to apply to (weak or unreviewed
matches) go back to where they were afterwards, with no card left in Needs you; jobs you had
approved, or that failed before, keep the result like any other run.
"""

import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.email_apply import mailto_address
from linkit_all.apply.handlers import HANDLERS
from linkit_all.apply.runner import Applier, ApplyBlocked, _web_url
from linkit_all.core.config import Settings
from linkit_all.core.models import ActionItem, ActionStatus, Job, JobEvent, JobState, utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.matching.rank import Embed
from linkit_all.providers.base import LLMProvider

# Best candidates first: jobs that already failed, then ones the user wanted, then the rest.
_STATES = [
    JobState.failed,
    JobState.queued_apply,
    JobState.tailored,
    JobState.awaiting_review,
    JobState.scored,
    JobState.below_threshold,
]
AGENT = "form agent"  # every site without its own handler
# picked only for the test: put back afterwards
_GIVE_BACK = {JobState.awaiting_review, JobState.scored, JobState.below_threshold}


@dataclass
class ProbeRow:
    job_id: int
    source: str
    host: str
    status: str
    detail: str
    code: str
    screenshot: str
    platform: str = ""  # what filled the form: an ATS handler, "form agent" or "email"
    seconds: float = 0.0


def pick(db: sessionmaker[Session], per_source: int = 1, ids: list[int] | None = None) -> list[int]:
    """Up to `per_source` jobs per source with a web or email apply link (or exactly `ids`)."""
    with db() as s:
        if ids:
            return [j.id for j in s.scalars(select(Job).where(Job.id.in_(ids)))]
        jobs = list(s.scalars(select(Job).where(Job.state.in_(_STATES))))
    rank = {st: i for i, st in enumerate(_STATES)}
    jobs.sort(key=lambda j: (rank[j.state], -(j.score or 0), -(j.data.get("rank") or 0)))
    out: dict[str, list[int]] = defaultdict(list)
    for j in jobs:
        link = j.data.get("apply_url") or j.url
        if (mailto_address(link) or _web_url(link)) and len(out[j.source]) < per_source:
            out[j.source].append(j.id)
    return [i for group in out.values() for i in group]


def _queue(db: sessionmaker[Session], job_id: int) -> JobState:
    """Queue the job for the test; returns the state it had."""
    with db.begin() as s:
        job = s.get_one(Job, job_id)
        before = job.state
        if job.state not in (JobState.queued_apply, JobState.tailored):
            transition(s, job, JobState.queued_apply, "picked for the apply test", code="probe")
        job.data = {k: v for k, v in job.data.items() if k != "dry_run_at"}  # practice it again
    return before


def give_back(db: sessionmaker[Session], job_id: int, state: JobState) -> None:
    """Put a job that was only borrowed for the test back in `state` and close its cards."""
    with db.begin() as s:
        job = s.get_one(Job, job_id)
        for item in s.scalars(
            select(ActionItem).where(
                ActionItem.job_id == job_id, ActionItem.status == ActionStatus.open
            )
        ):
            item.status, item.resolved_at = ActionStatus.dismissed, utcnow()
        if job.state != state:
            msg = "back where it was after the apply test"
            s.add(JobEvent(job=job, from_state=job.state, to_state=state, message=msg,
                           code="probe_restored"))  # fmt: skip
            job.state = state


def give_back_all(db: sessionmaker[Session]) -> int:
    """Put back every job an earlier test borrowed and left elsewhere (e.g. a test run from
    before this existed). Jobs you acted on since are left alone. Returns how many moved."""
    with db() as s:
        borrowed = s.execute(
            select(JobEvent.job_id, JobEvent.from_state, JobEvent.id)
            .where(JobEvent.code == "probe")
            .order_by(JobEvent.id)
        ).all()
        latest = {job_id: (state, event_id) for job_id, state, event_id in borrowed}
        todo = []
        for job_id, (state, event_id) in latest.items():
            later = s.scalars(
                select(JobEvent.code).where(JobEvent.job_id == job_id, JobEvent.id > event_id)
            ).all()
            if (
                state in _GIVE_BACK
                and "probe_restored" not in later
                and not ({"applied_by_hand", "skipped"} & set(later))
            ):
                todo.append((job_id, state))
    for job_id, state in todo:
        give_back(db, job_id, state)
    return len(todo)


def _row(
    db: sessionmaker[Session], job_id: int, status: str, detail: str, seconds: float = 0.0
) -> ProbeRow:
    with db() as s:
        job = s.get_one(Job, job_id)
        item = s.scalars(
            select(ActionItem).where(ActionItem.job_id == job_id).order_by(ActionItem.id.desc())
        ).first()
        last = s.scalars(
            select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id.desc())
        ).first()
        code = (item.code if status == "needs_user" and item else None) or (last and last.code)
        shots = (last.artifacts if last else None) or (item.artifacts if item else None) or [""]
        link = job.data.get("apply_url") or job.url
        host = "email" if mailto_address(link) else urlparse(link).netloc
        platform = "email" if host == "email" else job.ats if job.ats in HANDLERS else AGENT
        return ProbeRow(
            job_id, job.source, host, status, detail, code or "", shots[-1], platform, seconds
        )


async def probe(
    db: sessionmaker[Session],
    settings: Settings,
    cfg: SearchConfig,
    provider: LLMProvider,
    embed: Embed,
    job_ids: list[int],
) -> list[ProbeRow]:
    """Practice-mode apply of each job, one at a time. The CV is sent as uploaded (no
    tailoring) so the test spends AI only on reading the forms."""
    # ponytail: one job at a time; parallel sites if a full probe gets too slow
    test = cfg.model_copy(deep=True)
    test.apply.live, test.apply.tailor_cv = False, False
    rows = []
    async with Applier(db, settings, test, provider, embed) as applier:
        for job_id in job_ids:
            before = _queue(db, job_id)
            start = time.perf_counter()
            try:
                outcome = await applier.apply(job_id)
                took = time.perf_counter() - start
                rows.append(_row(db, job_id, outcome.status, outcome.message, took))
            except ApplyBlocked as e:
                # The AI is out of quota (or a tool is missing): every job after this one would
                # end the same way, so stop here. The job waits, untouched; no row for it.
                if before in _GIVE_BACK:
                    give_back(db, job_id, before)
                logger.warning("apply test stopped at job {}: {}", job_id, e)
                break
            except Exception as e:  # one broken site must not end the test
                took = time.perf_counter() - start
                rows.append(_row(db, job_id, "error", f"{type(e).__name__}: {e}", took))
            if before in _GIVE_BACK:
                give_back(db, job_id, before)
    return rows


def report(rows: list[ProbeRow], out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"probe_{datetime.now():%Y%m%d-%H%M}.md"
    lines = [
        "| job | source | apply host | result | code | detail | screenshot |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (r.status, r.source)):
        detail = r.detail.replace("|", "/").replace("\n", " ")[:160]
        lines.append(
            f"| {r.job_id} | {r.source} | {r.host} | {r.status} | {r.code} | {detail} "
            f"| {r.screenshot} |"
        )
    path.write_text("# Apply test (Practice mode)\n\n" + "\n".join(lines) + "\n", "utf-8")
    return path


def scorecard(rows: list[ProbeRow], when: datetime) -> str:
    """One Markdown page: per platform, how many practice applications were filled to the last
    step, how many wait for the user and why, how many failed. Counts only, no job details."""
    by: dict[str, list[ProbeRow]] = defaultdict(list)
    for r in rows:
        by[r.platform or AGENT].append(r)
    out = [
        "# Apply scorecard",
        "",
        f"Practice mode, {when:%Y-%m-%d}: {len(rows)} real job postings, forms filled and "
        "nothing submitted. The CV was sent as uploaded.",
        "",
        "| platform | tried | filled to the end | needs you | failed | skipped | median time |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, group in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        n = Counter(r.status for r in group)
        took = median(r.seconds for r in group)
        out.append(
            f"| {name} | {len(group)} | {n['dry_run']} ({n['dry_run'] / len(group):.0%}) "
            f"| {n['needs_user']} | {n['failed'] + n['error']} | {n['skipped']} | {took:.0f} s |"
        )
    stops = Counter(
        (r.platform or AGENT, r.status, r.code or "-") for r in rows if r.status != "dry_run"
    )
    if stops:
        out += ["", "## Why the others stopped", "", "| platform | result | reason | jobs |",
                "|---|---|---|---|"]  # fmt: skip
        out += [
            f"| {platform} | {status} | {code} | {count} |"
            for (platform, status, code), count in sorted(stops.items(), key=lambda kv: -kv[1])
        ]
    return "\n".join(out) + "\n"
