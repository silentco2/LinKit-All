"""Apply test across sources: one job per source, run in Practice mode, one report.

Shows where each kind of application gets to (filled and ready to submit, parked and why, or
failed) without submitting anything. Jobs you had not chosen to apply to (weak or unreviewed
matches) go back to where they were afterwards, with no card left in Needs you; jobs you had
approved, or that failed before, keep the result like any other run.
"""

import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any
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
from linkit_all.core.state import TERMINAL, transition
from linkit_all.matching.rank import Embed
from linkit_all.matching.trash import not_trash
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
SIGNUP = "dry_run_signup"  # reached a sign-up page: as far as practice mode goes
CLOSED = ("posting_gone", "job_closed")  # the ad was gone: trashed, nothing to apply to
# Never the app's to finish alone: LinkedIn (the user applies in their own browser) and a
# question only the user can answer. Listed, but left out of the pass rate.
# knockout: the form would reject you (e.g. 9 years asked, 8 given): "Apply anyway" is your call
YOURS = ("apply_in_browser", "apply_in_browser_offsite", "unknown_question", "knockout")
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
    timings: dict[str, Any] = field(default_factory=dict)  # core.timing summary of the job


def pick(
    db: sessionmaker[Session],
    per_source: int = 1,
    ids: list[int] | None = None,
    fresh: bool = False,
    per_site: int | None = None,
) -> list[int]:
    """Up to `per_source` jobs per source with a web or email apply link (or exactly `ids`).
    `fresh`: only jobs no earlier test has tried, so a new sample is really new. `per_site`:
    at most this many per apply site, so one site's many look-alike forms do not fill it."""
    with db() as s:
        if ids:
            return [j.id for j in s.scalars(select(Job).where(Job.id.in_(ids)))]
        query = select(Job).where(Job.state.in_(_STATES), not_trash())
        if fresh:
            tried = select(JobEvent.job_id).where(JobEvent.code == "probe")
            query = query.where(Job.id.not_in(tried))
        jobs = list(s.scalars(query))
    rank = {st: i for i, st in enumerate(_STATES)}
    jobs.sort(key=lambda j: (rank[j.state], -(j.score or 0), -(j.data.get("rank") or 0)))
    out: dict[str, list[int]] = defaultdict(list)
    sites: Counter[str] = Counter()
    for j in jobs:
        link = j.data.get("apply_url") or j.url
        if not (mailto_address(link) or _web_url(link)) or len(out[j.source]) >= per_source:
            continue
        if per_site is not None:
            if sites[site := site_of(link)] >= per_site:
                continue
            sites[site] += 1
        out[j.source].append(j.id)
    return [i for group in out.values() for i in group]


def site_of(link: str) -> str:
    """One apply site: the host plus the first path part (a company's board on a shared ATS)."""
    if address := mailto_address(link):
        return "email:" + address.rsplit("@", 1)[-1]
    u = urlparse(link)
    return f"{u.netloc}/{u.path.strip('/').split('/')[0]}"


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
        if job.data.get("trash"):
            return  # e.g. the ad turned out closed: it stays in the trash
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
        return ProbeRow(job_id, job.source, host, status, detail, code or "", shots[-1], platform,
                        seconds, dict(job.data.get("timings") or {}))  # fmt: skip


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
            with db() as s:
                done = s.get_one(Job, job_id).state
            if done in TERMINAL:  # e.g. an ad an earlier test found closed: it stays in the trash
                rows.append(_row(db, job_id, done.value, "finished earlier, not tried again"))
                continue
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
        "| job | source | apply host | result | code | detail | time | slowest steps "
        "| screenshot |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (r.status, r.source)):
        detail = r.detail.replace("|", "/").replace("\n", " ")[:160]
        slow = "; ".join(
            f"{x['step']} {x['s']:.0f} s" + (f" ({x['note']})" if x.get("note") else "")
            for x in (r.timings.get("slow") or [])[:3]
        ).replace("|", "/")
        lines.append(
            f"| {r.job_id} | {r.source} | {r.host} | {r.status} | {r.code} | {detail} "
            f"| {r.seconds:.0f} s | {slow} | {r.screenshot} |"
        )
    path.write_text("# Apply test (Practice mode)\n\n" + "\n".join(lines) + "\n", "utf-8")
    return path


def scorecard(rows: list[ProbeRow], when: datetime) -> str:
    """One Markdown page: per platform, how many practice applications passed, how many wait for
    the user and why, how many failed. Counts only, no job details.

    Passed = filled to the last step, reached a sign-up form (practice mode never creates an
    account; real mode signs up and goes on) or found the ad closed (it goes to the trash)."""
    by: dict[str, list[ProbeRow]] = defaultdict(list)
    for r in rows:
        by[r.platform or AGENT].append(r)
    out = [
        "# Apply scorecard",
        "",
        f"Practice mode, {when:%Y-%m-%d}: {len(rows)} real job postings, forms filled and "
        "nothing submitted. The CV was sent as uploaded.",
        "",
        "| platform | tried | passed | filled to the end | reached sign-up | ad closed "
        "| needs you | failed | skipped | median time |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, group in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        n = Counter(r.status for r in group)
        signup = sum(r.code == SIGNUP for r in group)
        filled = n["dry_run"] - signup
        closed = sum(r.status == "skipped" and r.code in CLOSED for r in group)
        passed = filled + signup + closed
        took = median(r.seconds for r in group)
        out.append(
            f"| {name} | {len(group)} | {passed} ({passed / len(group):.0%}) | {filled} | {signup} "
            f"| {closed} | {n['needs_user']} | {n['failed'] + n['error']} "
            f"| {n['skipped'] - closed} | {took:.0f} s |"
        )
    out += ["", rate_line(rows)]
    stops = Counter(
        (r.platform or AGENT, r.status, r.code or "-")
        for r in rows
        if r.status != "dry_run" or r.code == SIGNUP
    )  # closed ads and sign-ups passed, but the reasons still show what happened
    if stops:
        out += ["", "## Why the others stopped", "", "| platform | result | reason | jobs |",
                "|---|---|---|---|"]  # fmt: skip
        out += [
            f"| {platform} | {status} | {code} | {count} |"
            for (platform, status, code), count in sorted(stops.items(), key=lambda kv: -kv[1])
        ]
    out += step_times(rows)
    return "\n".join(out) + "\n"


def passed(r: ProbeRow) -> bool:
    """Went as far as practice mode allows: filled, reached a sign-up form, or the ad was gone."""
    return r.status == "dry_run" or (r.status == "skipped" and r.code in CLOSED)


def rate_line(rows: list[ProbeRow]) -> str:
    counted = [r for r in rows if r.code not in YOURS]
    browser = sum(r.code in YOURS[:2] for r in rows)
    asked = sum(r.code in YOURS[2:] for r in rows)
    ok = sum(passed(r) for r in counted)
    share = f"{ok / len(counted):.0%}" if counted else "-"
    return (
        f"**Pass rate: {ok} of {len(counted)} ({share})** of the jobs the app may finish on its "
        f"own. Not counted: {browser} on sites the app never drives, such as LinkedIn (you "
        f"apply in your own browser) and {asked} "
        "waiting for an answer or a decision only you can give."
    )


_NUM = re.compile(r"\d+(\.\d+)?")


def step_times(rows: list[ProbeRow]) -> list[str]:
    """Where the time went: per step, the median seconds a job spent in it, its share of all
    the time, and the most common reasons given for the slow ones."""
    timed = [r.timings for r in rows if r.timings.get("steps")]
    if not timed:
        return []
    per: dict[str, list[float]] = defaultdict(list)
    for t in timed:
        for name, (secs, _n) in t["steps"].items():
            per[name].append(secs)
    why: dict[str, Counter[str]] = defaultdict(Counter)
    for t in timed:
        for x in t.get("slow") or []:
            if x.get("note"):  # numbers vary per job; the wording groups them
                why[x["step"]][_NUM.sub("N", x["note"])] += 1
    everything = sum(sum(v) for v in per.values()) or 1.0
    totals = [t["total"] for t in timed]
    out = [
        "",
        "## Where the time goes",
        "",
        f"{len(timed)} jobs timed. Median {median(totals):.0f} s per job, slowest "
        f"{max(totals):.0f} s. A step's time leaves out the steps inside it, so the shares add "
        'up to 100%. "other" is time outside any named step.',
        "",
        "| step | jobs | median per job | slowest | share of all time "
        "| why the slow ones took long |",
        "|---|---|---|---|---|---|",
    ]
    for name, secs in sorted(per.items(), key=lambda kv: -sum(kv[1])):
        reasons = "; ".join(f"{text} ({n} jobs)" for text, n in why[name].most_common(2))
        out.append(
            f"| {name} | {len(secs)} | {median(secs):.1f} s | {max(secs):.0f} s "
            f"| {sum(secs) / everything:.0%} | {reasons.replace('|', '/')} |"
        )
    return out
