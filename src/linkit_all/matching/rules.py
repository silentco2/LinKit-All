"""Hard rules from [filters]: free, deterministic, run before any ranking or AI."""

import re
from datetime import datetime, timedelta
from typing import Any

from linkit_all.core import fx
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
_PERIOD = {"year": "year", "yearly": "year", "month": "month", "monthly": "month",
           "week": "week", "weekly": "week", "day": "day", "daily": "day",
           "hour": "hour", "hourly": "hour"}  # fmt: skip


def seniority(title: str) -> Seniority | None:
    """The level a title states, or None when it names none ("Frontend Developer")."""
    t = title.lower()
    return next((level for pattern, level in _SENIORITY if pattern.search(t)), None)


def expectation_of(answers: dict[str, Any], cfg: SearchConfig) -> tuple[float, str] | None:
    """The monthly pay you expect and its currency, from the saved answers; None if unset."""
    raw = str(answers.get("salary_expectation") or "").lower()
    number = re.sub(r"[^\d.]", "", raw)
    try:
        amount = float(number) * (1000 if re.search(r"\dk\b", raw.replace(" ", "")) else 1)
    except ValueError:
        return None
    currency = str(answers.get("salary_currency") or cfg.filters.salary_currency).upper()
    return (amount, currency) if amount > 0 else None


def rule_violation(
    job: Job, cfg: SearchConfig, now: datetime, expectation: tuple[float, str] | None = None
) -> str | None:
    """Why the job fails the hard filters, or None if it passes. `expectation` is
    `expectation_of(answers)`; it is the salary floor when none is set and the user opted in."""
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
    hours = cfg.search.posted_within_hours
    if hours and job.posted_at and job.posted_at < now - timedelta(hours=hours):
        return f"posted more than {hours} hours ago"
    floor: float = f.salary_floor_monthly
    currency = f.salary_currency
    if not floor and f.skip_below_expectation and expectation:
        floor, currency = expectation
    top, period = job.data.get("salary_max"), _PERIOD.get(job.data.get("salary_interval") or "year")
    posted = str(job.data.get("salary_currency") or "").upper()
    # Unknown to the rates table (or no currency stated): never rejected.
    if floor and top and period and posted:
        month = fx.monthly(top, period)
        pay = month if posted == currency else fx.convert(month, posted, currency)
        if pay is not None and pay < floor:
            return f"salary up to {pay:,.0f} {currency}/month is below your floor"
    if norm_company(job.company) in {norm_company(c) for c in f.company_blacklist}:
        return "company is blacklisted"
    return None
