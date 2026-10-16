"""Hard rules from [filters]: free, deterministic, run before any ranking or AI."""

import re
from datetime import datetime, timedelta

from linkit_all.core.models import Job
from linkit_all.core.search import SearchConfig, Seniority
from linkit_all.sources.base import remote_from_text
from linkit_all.sources.text import norm_company

# Checked in order; the first hit wins ("Senior Manager" is a manager).
_SENIORITY: list[tuple[re.Pattern[str], Seniority]] = [
    (re.compile(r"\b(intern|internship|trainee)\b"), "intern"),
    (re.compile(r"\b(vp|vice president|chief|cto|ceo|cfo|coo)\b"), "executive"),
    (re.compile(r"\b(manager|head of|director)\b"), "manager"),
    (re.compile(r"\b(lead|staff|principal|architect)\b"), "lead"),
    (re.compile(r"\b(senior|sr)\b"), "senior"),
    (re.compile(r"\b(junior|jr|entry|graduate|fresh)\b"), "junior"),
]
_PER_YEAR = {"year": 1, "yearly": 1, "month": 12, "monthly": 12, "week": 52, "weekly": 52,
             "day": 260, "daily": 260, "hour": 2080, "hourly": 2080}  # fmt: skip


def seniority(title: str) -> Seniority | None:
    """The level a title states, or None when it names none ("Frontend Developer")."""
    t = title.lower()
    return next((level for pattern, level in _SENIORITY if pattern.search(t)), None)


def rule_violation(job: Job, cfg: SearchConfig, now: datetime) -> str | None:
    """Why the job fails the hard filters, or None if it passes."""
    f = cfg.filters
    title = job.title.lower()
    if f.title_include and not any(w.lower() in title for w in f.title_include):
        return "title has none of the include words"
    if hit := next((w for w in f.title_exclude if w.lower() in title), None):
        return f"title contains excluded word {hit!r}"
    # Hard rules reject only on a known mismatch: most job sites leave the work mode blank, and
    # treating blank as on-site dropped nearly every job under a "remote" filter.
    remote = job.data.get("remote") or remote_from_text(job.location, job.title)
    if remote and remote not in f.work_modes:
        return f"work mode {remote} is not one you chose"
    where = f"{job.location} {job.data.get('remote') or ''}".lower()
    if f.locations and not any(loc.lower() in where for loc in f.locations):
        return f"location {job.location!r} not in your locations"
    if f.seniority and (level := seniority(job.title)) and level not in f.seniority:
        return f"seniority {level} not wanted"
    if job.posted_at and job.posted_at < now - timedelta(days=cfg.search.posted_within_days):
        return f"posted more than {cfg.search.posted_within_days} days ago"
    top, per = job.data.get("salary_max"), _PER_YEAR.get(job.data.get("salary_interval") or "year")
    # ponytail: no FX conversion; a posting in another currency (or none) is never rejected.
    # Upgrade path: a rates table, only if mixed-currency boards turn out common.
    same = str(job.data.get("salary_currency") or "").upper() == f.salary_currency
    if f.salary_floor_monthly and top and per and same and top * per / 12 < f.salary_floor_monthly:
        return f"salary up to {top * per / 12:,.0f} {f.salary_currency}/month is below your floor"
    if norm_company(job.company) in {norm_company(c) for c in f.company_blacklist}:
        return "company is blacklisted"
    return None
