"""The trash: jobs the user never sees again. Nothing is deleted, so later searches still dedupe
and filter against them.

`data["trash"]` says why: "reported" (the user reported it), "company" (blacklisted company) or
"off_title" (nothing like the titles searched for). Jobs already applied to are hidden by state.
"""

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import ActionItem, ActionStatus, Job, JobState
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.sources.text import norm_company

# Thresholds from 27,000 real titles against four developer searches: no single similarity cut
# separates them, so a shared word lowers the bar. A wrongly hidden job is lost for good, so a few
# near misses ("Sales Engineer") are left for the AI score to mark down.
SHARED_ROLE_FIT = 0.40  # shares only a role word: "Senior Software Engineer - Python"
NO_WORD_FIT = 0.55  # shares no word: "Product Builder"
# Words too common to make two titles related on their own.
_GENERIC = frozenset(
    [
        "developer",
        "manager",
        "specialist",
        "analyst",
        "consultant",
        "officer",
        "assistant",
        "coordinator",
        "executive",
        "lead",
        "senior",
        "junior",
        "head",
        "web",
        "software",
        "technical",
        "and",
        "of",
        "the",
        "in",
        "for",
        "to",
    ]
)
_JOINED = re.compile(r"\b(full|front|back)[\s-]+(stack|end)\b")
_SAME_ROLE = dict.fromkeys(
    [
        "engineer",
        "programmer",
        "dev",
        "desarrollador",
        "desenvolvedor",
        "développeur",
        "entwickler",
        "разработчик",
        "مطور",
        "مهندس",
    ],
    "developer",
)
# Past these states nothing is left to hide or stop, or a browser is on it right now.
_LEFT_ALONE = (JobState.applied, JobState.applying)
# Still on its way to an application: leaves the pipeline, so no AI or browser is spent on it.
_ON_THE_WAY = (JobState.ranked, JobState.scored, JobState.awaiting_review, JobState.queued_apply,
               JobState.tailored, JobState.needs_user)  # fmt: skip
UNKNOWN = norm_company("Unknown")  # many companies (posts that name none): never blacklisted


def visible() -> ColumnElement[bool]:
    """The one rule for every list of jobs the user can see."""
    return and_(Job.state != JobState.applied, not_trash())


def not_trash() -> ColumnElement[bool]:
    kept: ColumnElement[bool] = Job.data["trash"].as_string().is_(None)
    return kept


def _words(title: str) -> set[str]:
    text = _JOINED.sub(r"\1\2", title.lower()).replace(".", "")  # Next.js, Full-Stack, Front End
    return {_SAME_ROLE.get(w, w) for w in re.findall(r"\w+", text)}


def wanted_titles(cfg: SearchConfig) -> list[str]:
    titles = [*cfg.search.queries, *cfg.filters.title_include]
    return [t for t in dict.fromkeys(titles) if t.strip()]


def off_titles(titles: Iterable[str], wanted: list[str], embed: Any) -> set[str]:
    """Those of `titles` unrelated to every wanted title. No wanted titles: nothing is off."""
    if not wanted:
        return set()
    want = set[str]().union(*map(_words, wanted))
    specific = want - _GENERIC
    maybe = [t for t in titles if not _words(t) & specific]  # a shared skill word needs no model
    if not maybe:
        return set()
    fits = (embed(maybe) @ embed(wanted).T).max(axis=1)
    return {
        t for t, fit in zip(maybe, fits, strict=True)
        if fit < (SHARED_ROLE_FIT if _words(t) & want else NO_WORD_FIT)
    }  # fmt: skip


def _drop(s: Session, job: Job) -> None:
    """Take a job in the trash out of the pipeline, along with anything it waits on the user for."""
    transition(s, job, JobState.skipped, "not a job you are looking for", code="trashed")
    for item in s.scalars(select(ActionItem).filter_by(job_id=job.id, status=ActionStatus.open)):
        item.status = ActionStatus.dismissed


def sweep(db: sessionmaker[Session], cfg: SearchConfig, embed: Any) -> int:
    """Bring every job's trash mark up to date; returns how many left the pipeline for it.

    Titles are embedded once per set of wanted titles (`title_key`): a full pass over 27,000
    titles takes about 3 minutes on a CPU, so it runs outside any request.
    """
    wanted = wanted_titles(cfg)
    key = hashlib.sha256(json.dumps(wanted).encode()).hexdigest()[:12]
    blocked = {norm_company(c) for c in cfg.filters.company_blacklist}
    with db() as s:
        rows = s.execute(
            select(Job.title, Job.data["title_key"].as_string()).where(
                Job.state.not_in(_LEFT_ALONE)
            )
        ).all()
    # ponytail: re-embeds everything when the wanted titles change; cache vectors if that hurts
    fresh = sorted({title for title, seen in rows if seen != key})
    off = off_titles(fresh, wanted, embed)
    dropped = 0
    with db.begin() as s:
        for job in s.scalars(select(Job).where(Job.state.not_in(_LEFT_ALONE))):
            data = dict(job.data)
            if data.get("title_key") != key:
                data["title_key"] = key
                data["off_title"] = job.title in off
            why = data.get("trash")
            if why != "reported":
                why = ("company" if norm_company(job.company) in blocked else None) or (
                    "off_title" if data["off_title"] else None
                )
                if why:
                    data["trash"] = why
                else:
                    data.pop("trash", None)
            if data != job.data:
                job.data = data
            if why and job.state in _ON_THE_WAY:
                _drop(s, job)
                dropped += 1
    return dropped
