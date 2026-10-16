"""Reports (CLAUDE.md 5.8): pure functions over a Session, plus CSV and PDF export.

Exports hold job metadata only. Never CV text, answers, passwords or email contents.
"""

import csv
import io
from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Any

import pymupdf
from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from linkit_all.core.models import Job, JobEvent, JobState, Run, utcnow

# Job states at or past each funnel step.
RANKED = {JobState.ranked, JobState.scored, JobState.below_threshold, JobState.awaiting_review,
          JobState.queued_apply, JobState.tailored, JobState.applying, JobState.needs_user,
          JobState.applied, JobState.failed, JobState.skipped}  # fmt: skip
TO_APPLY = {JobState.queued_apply, JobState.tailored, JobState.applying, JobState.needs_user,
            JobState.applied, JobState.failed}  # fmt: skip
OUTCOMES = (JobState.applied, JobState.failed, JobState.skipped, JobState.needs_user)
OVER_TIME_DAYS = 90
BOARD_LIMIT = 100


def _midnight(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time())


def _conds(run_id: int | None, since: date | None) -> list[ColumnElement[bool]]:
    conds: list[ColumnElement[bool]] = []
    if run_id is not None:
        conds.append(Job.run_id == run_id)
    if since is not None:
        conds.append(Job.created_at >= _midnight(since))
    return conds


def _grouped(
    s: Session,
    key: InstrumentedAttribute[Any],
    conds: Sequence[ColumnElement[bool]],
    limit: int | None,
) -> list[dict[str, Any]]:
    """Per-key found + applied/failed/skipped/needs_user counts, biggest first."""
    rows = s.execute(select(key, Job.state, func.count()).where(*conds).group_by(key, Job.state))
    table: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"found": 0, **{str(o): 0 for o in OUTCOMES}}
    )
    for name, state, n in rows:
        row = table[name or "unknown"]
        row["found"] += n
        if state in OUTCOMES:
            row[str(state)] += n
    out = [{"name": name, **row} for name, row in table.items()]
    if limit:  # a board with no apply outcome yet is just noise
        out = [r for r in out if any(r[str(o)] for o in OUTCOMES)]
    out.sort(key=lambda r: (-r["found"], r["name"]))
    return out[:limit]


def _per_run(s: Session, since: date | None) -> list[dict[str, Any]]:
    q = select(Run).order_by(Run.id.desc()).limit(50)
    if since is not None:
        q = q.where(Run.started_at >= _midnight(since))
    runs = list(s.scalars(q))
    ids = [r.id for r in runs]
    counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for run_id, state, n in s.execute(
        select(Job.run_id, Job.state, func.count())
        .where(Job.run_id.in_(ids))
        .group_by(Job.run_id, Job.state)
    ):
        if run_id is not None:
            counts[run_id][str(state)] = n
    return [
        {
            "run_id": r.id,
            "status": str(r.status),
            "started_at": r.started_at.isoformat(),
            "found": sum(counts[r.id].values()),
            **{str(o): counts[r.id][str(o)] for o in OUTCOMES},
        }
        for r in runs
    ]


def _over_time(s: Session, run_id: int | None, since: date | None) -> list[dict[str, Any]]:
    today = utcnow().date()
    first = today - timedelta(days=OVER_TIME_DAYS - 1)
    if since:
        first = max(since, first)
    q: Select[Any] = (
        select(func.date(JobEvent.at), JobEvent.to_state, func.count())
        .where(JobEvent.to_state.in_(OUTCOMES), JobEvent.at >= _midnight(first))
        .group_by(func.date(JobEvent.at), JobEvent.to_state)
    )
    if run_id is not None:
        q = q.join(Job, Job.id == JobEvent.job_id).where(Job.run_id == run_id)
    days: dict[str, dict[str, int]] = {}
    for i in range((today - first).days + 1):
        days[(first + timedelta(days=i)).isoformat()] = {str(o): 0 for o in OUTCOMES}
    for day, state, n in s.execute(q):
        if day in days:
            days[day][str(state)] = n
    return [{"date": d, **v} for d, v in days.items()]


def build_report(
    s: Session, run_id: int | None = None, since: date | None = None
) -> dict[str, Any]:
    conds = _conds(run_id, since)
    states = dict(
        s.execute(select(Job.state, func.count()).where(*conds).group_by(Job.state)).all()
    )
    tiers = dict(
        s.execute(
            select(Job.tier, func.count()).where(Job.tier.is_not(None), *conds).group_by(Job.tier)
        ).all()
    )
    scored = s.scalar(select(func.count()).where(Job.score.is_not(None), *conds)) or 0
    by_source = s.execute(
        select(Job.source, Job.state, func.count()).where(*conds).group_by(Job.source, Job.state)
    ).all()
    sources: dict[str, dict[str, int]] = {}
    for source, state, count in by_source:
        row = sources.setdefault(source, {"total": 0})
        row["total"] += count
        row[str(state)] = count
    return {
        "funnel": [
            {"step": "Found", "count": sum(states.values())},
            {"step": "Passed filters", "count": sum(states.get(x, 0) for x in RANKED)},
            {"step": "AI scored", "count": scored},
            {"step": "Queued to apply", "count": sum(states.get(x, 0) for x in TO_APPLY)},
            {"step": "Applied", "count": states.get(JobState.applied, 0)},
        ],
        "tiers": {str(k): v for k, v in tiers.items()},
        "states": {str(k): v for k, v in states.items()},
        "sources": sources,
        "per_platform": {
            "source": _grouped(s, Job.source, conds, None),
            "ats": _grouped(s, Job.ats, conds, None),
        },
        "per_board": _grouped(s, Job.company, conds, BOARD_LIMIT),
        "per_run": _per_run(s, since),
        "over_time": _over_time(s, run_id, since),
        "filter": {"run_id": run_id, "since": since.isoformat() if since else None},
    }


# --- exports ---------------------------------------------------------------------------

CSV_COLUMNS = ["job_id", "title", "company", "source", "ats", "state", "score", "tier",
               "applied_at", "last_event_at", "url"]  # fmt: skip


def _safe(v: Any) -> Any:
    """Stop spreadsheets running a job title that starts with = + - @ as a formula."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v


def export_csv(s: Session, run_id: int | None = None, since: date | None = None) -> str:
    last = (
        select(func.max(JobEvent.at))
        .where(JobEvent.job_id == Job.id)
        .correlate(Job)
        .scalar_subquery()
    )
    applied_at = (
        select(func.max(JobEvent.at))
        .where(JobEvent.job_id == Job.id, JobEvent.to_state == JobState.applied)
        .correlate(Job)
        .scalar_subquery()
    )
    q = (
        select(Job, applied_at, last)
        .where(Job.state.in_(TO_APPLY | {JobState.skipped}), *_conds(run_id, since))
        .order_by(Job.id)
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for job, applied, last_at in s.execute(q):
        w.writerow([
            job.id, _safe(job.title), _safe(job.company), job.source, job.ats or "",
            str(job.state), "" if job.score is None else job.score,
            str(job.tier) if job.tier else "",
            applied.isoformat() if applied else "", last_at.isoformat() if last_at else "",
            job.url,
        ])  # fmt: skip
    return buf.getvalue()


def _table(header: list[str], rows: list[list[Any]]) -> list[str]:
    cells = [header] + [[str(c) for c in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(header))]
    return [
        "  ".join(
            c.ljust(w) if i == 0 else c.rjust(w)
            for i, (c, w) in enumerate(zip(r, widths, strict=True))
        )
        for r in cells
    ]


def export_pdf(s: Session, run_id: int | None = None, since: date | None = None) -> bytes:
    rep = build_report(s, run_id, since)
    scope = f"run #{run_id}" if run_id is not None else "all runs"
    lines = [
        "LinKit All - application report",
        f"Generated {utcnow():%Y-%m-%d %H:%M} UTC. Scope: {scope}"
        + (f", since {since.isoformat()}" if since else ", all time"),
        "",
        "Funnel",
        *_table(["Step", "Jobs"], [[f["step"], f["count"]] for f in rep["funnel"]]),
        "",
        "By platform (job source)",
        *_table(
            ["Source", "Found", "Applied", "Failed", "Skipped", "Needs you"],
            [
                [r["name"], r["found"], r["applied"], r["failed"], r["skipped"], r["needs_user"]]
                for r in rep["per_platform"]["source"]
            ],
        ),
        "",
        "By ATS",
        *_table(
            ["ATS", "Found", "Applied", "Failed", "Skipped", "Needs you"],
            [
                [r["name"], r["found"], r["applied"], r["failed"], r["skipped"], r["needs_user"]]
                for r in rep["per_platform"]["ats"]
            ],
        ),
    ]
    doc = pymupdf.open()
    page = doc.new_page()
    y = 50.0
    for i, line in enumerate(lines):
        if y > 790:
            page, y = doc.new_page(), 50.0
        size = 15 if i == 0 else 9
        page.insert_text((40, y), line[:110], fontname="cour", fontsize=size)
        y += size + 5
    data = bytes(doc.tobytes())
    doc.close()
    return data
