"""Employer replies -> outcomes on applied jobs (opt-in, `email.read_replies`). Rules only: the
mail's subject and text are read on this machine, never sent to the AI and never logged. A mail
counts only when it names exactly one applied job's company (by sender domain or by name on a
word boundary, so "HP" never matches "PHP"); the role title breaks ties. Mail is applied oldest
first, so the latest reply wins, and an outcome the user set by hand is never changed.
Logic adapted from career-ops (MIT)."""

import asyncio
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.email_verify import (
    EmailLoginError,
    _html_text,
    _imap_rows,
    credentials,
    microsoft,
)
from linkit_all.apply.vault import Vault
from linkit_all.core.models import Job, JobState, Outcome
from linkit_all.core.search import EmailSection
from linkit_all.core.state import set_outcome
from linkit_all.sources.text import norm_company

Kind = Literal["rejected", "interview"]
MAX_MAILS = 500  # newest messages read per check

_REJECTED = re.compile(
    r"\b(?:unfortunately|regret to inform|not (?:be )?(?:moving|proceeding|progressing) forward"
    r"|decided (?:not to|to (?:move|proceed|go) forward with other)|other candidates"
    r"|not (?:been )?selected|position has been filled|will not be (?:moving|progressing)"
    r"|no longer (?:under )?consider)"
    r"|للأسف|نأسف لإبلاغك|لم يتم (?:اختيارك|قبولك)",
    re.I,
)
_INTERVIEW = re.compile(
    r"\b(?:invite you (?:to|for) (?:an? )?(?:interview|call|chat|conversation)"
    r"|(?:schedule|book|arrange) (?:an? |your )?"
    r"(?:interview|call|phone screen|time to (?:talk|chat))"
    r"|interview (?:invitation|invite|request)|next (?:step|round)s? (?:in|of) (?:the|our) process"
    r"|would (?:like|love) to (?:speak|talk|chat|meet) with you)"
    r"|دعوة (?:لإجراء )?مقابلة|نود (?:دعوتك|التحدث معك)",
    re.I,
)
_GENERIC_HOSTS = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com"}
_ATS_SENDERS = ("greenhouse", "lever", "ashby", "workday", "smartrecruiters", "icims", "workable")


def classify(subject: str, text: str) -> Kind | None:
    """A rejection wins over an interview phrase in one mail ("unfortunately ... next round")."""
    words = f"{subject}\n{text}"
    if _REJECTED.search(words):
        return "rejected"
    if _INTERVIEW.search(words):
        return "interview"
    return None


@dataclass(frozen=True)
class Applied:
    id: int
    company: str
    title: str


def _name_in(name: str, text: str) -> bool:
    words = name.split()
    if not words or (len(name) < 3 and not name.isupper()):
        return False
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text, re.I) is not None


def _from_company(sender: str, company: str) -> bool:
    host = sender.lower().rpartition("@")[2]
    if not host or host in _GENERIC_HOSTS:
        return False
    key = norm_company(company).replace(" ", "")
    labels = [label for label in host.split(".")[:-1] if label not in _ATS_SENDERS]
    return len(key) >= 2 and any(key == label.replace("-", "") for label in labels)


def match(sender: str, subject: str, text: str, jobs: list[Applied]) -> int | None:
    """The one applied job this mail is about, or None when no company or several match."""
    body = f"{subject}\n{text}"
    hits = [j for j in jobs if _from_company(sender, j.company) or _name_in(j.company, body)]
    companies = {norm_company(j.company) for j in hits}
    if len(companies) != 1:
        return None
    if len(hits) == 1:
        return hits[0].id
    titled = [j for j in hits if _name_in(j.title, body)]
    return titled[0].id if len(titled) == 1 else None


def apply_replies(
    db: sessionmaker[Session], mails: list[tuple[datetime, str, str, str]]
) -> dict[str, int]:
    """`mails`: (when, sender, subject, text). Sets outcomes; returns counts only."""
    counts = {"read": len(mails), "rejected": 0, "interview": 0}
    with db.begin() as s:
        rows = s.scalars(select(Job).where(Job.state == JobState.applied)).all()
        jobs = [Applied(j.id, j.company, j.title) for j in rows]
        by_id = {j.id: j for j in rows}
        for when, sender, subject, text in sorted(mails, key=lambda m: m[0]):
            kind = classify(subject, text)
            if kind is None or (jid := match(sender, subject, text, jobs)) is None:
                continue
            job = by_id[jid]
            applied_at = job.data.get("applied_at")
            if applied_at and when < _aware(datetime.fromisoformat(applied_at)):
                continue  # older than the application: about something else
            if job.data.get("outcome_by") == "user":
                continue
            if set_outcome(s, job, Outcome(kind), "email"):
                job.data = {**job.data, "outcome_by": "email"}
                counts[kind] += 1
    return counts


def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _since(db: sessionmaker[Session]) -> datetime | None:
    with db() as s:
        stamps = [
            j.data.get("applied_at")
            for j in s.scalars(select(Job).where(Job.state == JobState.applied))
        ]
    found = [_aware(datetime.fromisoformat(a)) for a in stamps if a]
    return min(found) - timedelta(days=1) if found else None


def _rows(
    cfg: EmailSection, user: str, secret: str, since: datetime
) -> list[tuple[datetime, str, str, str]]:
    if microsoft.is_host(cfg.imap_host):
        raw = microsoft.messages(secret, since, MAX_MAILS)
    else:
        raw = _imap_rows(cfg.imap_host, user, secret, since)
    return [
        (when, sender, subject, text or _html_text(html))
        for _, when, sender, subject, text, html in raw
    ]


async def read_replies(
    db: sessionmaker[Session], cfg: EmailSection, vault: Vault | None, profile_email: str
) -> dict[str, int]:
    """Check the inbox once. Never raises: a mail problem only skips this check."""
    if not cfg.read_replies or vault is None or not vault.unlocked():
        return {}
    since = _since(db)
    if since is None:
        return {}
    try:
        creds = credentials(cfg, vault, profile_email)
        if creds is None:
            return {}
        mails = await asyncio.to_thread(_rows, cfg, *creds, since)
    except (EmailLoginError, OSError, Exception) as e:
        logger.warning("reply check skipped ({})", type(e).__name__)
        return {}
    counts = apply_replies(db, mails)
    logger.info("reply check: {} mails read, {} rejections, {} interviews",
                counts["read"], counts["rejected"], counts["interview"])  # fmt: skip
    return counts
