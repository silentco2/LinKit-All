"""Hard rules from [filters]: free, deterministic, run before any ranking or AI."""

import re
from datetime import datetime, timedelta

from linkit_all.core.models import Job
from linkit_all.core.search import SearchConfig, Seniority
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


def seniority(title: str) -> Seniority:
    t = title.lower()
    return next((level for pattern, level in _SENIORITY if pattern.search(t)), "mid")


def rule_violation(job: Job, cfg: SearchConfig, now: datetime) -> str | None:
    """Why the job fails the hard filters, or None if it passes."""
    f = cfg.filters
    title = job.title.lower()
    if f.title_include and not any(w.lower() in title for w in f.title_include):
        return "title has none of the include words"
    if hit := next((w for w in f.title_exclude if w.lower() in title), None):
        return f"title contains excluded word {hit!r}"
    remote = job.data.get("remote") or "onsite"  # unknown: assume on-site
    if f.remote != "any" and remote != f.remote:
        return f"work mode {remote} is not {f.remote}"
    where = f"{job.location} {job.data.get('remote') or ''}".lower()
    if f.locations and not any(loc.lower() in where for loc in f.locations):
        return f"location {job.location!r} not in your locations"
    if f.seniority and (level := seniority(job.title)) not in f.seniority:
        return f"seniority {level} not wanted"
    if job.posted_at and job.posted_at < now - timedelta(days=cfg.search.posted_within_days):
        return f"posted more than {cfg.search.posted_within_days} days ago"
    top, per = job.data.get("salary_max"), _PER_YEAR.get(job.data.get("salary_interval") or "year")
    if f.salary_floor and top and per and top * per < f.salary_floor:
        return f"salary up to {top * per:,.0f}/year is below your floor"
    if norm_company(job.company) in {norm_company(c) for c in f.company_blacklist}:
        return "company is blacklisted"
    return None
