"""Job facts the board left blank (work mode, location, salary), read by the score call and kept
only when code can check them: the quote must be in the posting and must hold the value. A kept
fact fills the blank, then the hard rules run again (`score.py`). A fact can only make the filter
stricter, never clear a job: "AI can raise, never clear" (CLAUDE.md §5.3). Rules only here."""

import re
from typing import Any, Literal

from pydantic import BaseModel, field_validator

from linkit_all.core import geo
from linkit_all.core.models import Job
from linkit_all.sources.base import remote_from_text

MIN_QUOTE = 6
MAX_QUOTE = 300
Field = Literal["work_mode", "location", "salary"]
_MODE_WORDS = {
    "remote": ("remote", "work from home", "work from anywhere", "عن بعد", "عن بُعد"),
    "hybrid": ("hybrid", "هجين"),
    "onsite": ("on-site", "onsite", "on site", "in office", "in-office", "office-based",
               "office based", "من المقر", "في المكتب"),
}  # fmt: skip
_NEGATED = re.compile(r"\b(?:not|no|non)[\s-]+(?:an?\s+|fully\s+|100%\s+)*(?:remote|hybrid)")
_PERIOD_WORDS = {
    "year": ("year", "annual", "annum", "p.a", "/yr", "yearly"),
    "month": ("month", "/mo", "شهري", "شهر"),
    "week": ("week",),
    "day": ("day", "daily"),
    "hour": ("hour", "/hr", "/h "),
}
# Only symbols that name one currency; "$" could be USD, CAD, AUD... so it must be spelled out.
_SYMBOLS = {"€": "EUR", "£": "GBP", "₹": "INR"}
_NUMBER = re.compile(r"(\d{1,3}(?:[ ,.]\d{3})+|\d+(?:\.\d+)?)\s*([kK])?")


class Fact(BaseModel):
    value: str
    quote: str


class SalaryFact(BaseModel):
    min: float | None = None
    max: float | None = None
    currency: str = ""
    interval: Literal["year", "month", "week", "day", "hour"] = "year"
    quote: str = ""

    @field_validator("currency")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class JobFacts(BaseModel):
    """Only for facts the job was missing; each omitted when the posting does not state it."""

    work_mode: Fact | None = None  # value: remote | hybrid | onsite
    location: Fact | None = None
    salary: SalaryFact | None = None


def missing(job: Job) -> list[Field]:
    """The facts a hard rule could use that this job does not have."""
    out: list[Field] = []
    if not (job.data.get("remote") or remote_from_text(job.location, job.title)):
        out.append("work_mode")
    if not job.location.strip():
        out.append("location")
    if job.data.get("salary_max") is None and job.data.get("salary_min") is None:
        out.append("salary")
    return out


def _squash(text: str) -> str:
    return " ".join(text.lower().split())


def _quoted(quote: str, posting: str) -> bool:
    q = _squash(quote).strip(" .\"'…")
    return MIN_QUOTE <= len(q) <= MAX_QUOTE and q in _squash(posting)


def _numbers(quote: str) -> set[float]:
    out = set()
    for digits, k in _NUMBER.findall(quote):
        # "60,000", "60 000" and "60.000" are thousands; "4.5" is a decimal
        n = float(re.sub(r"[ ,.]", "", digits) if re.search(r"[ ,.]\d{3}$", digits) else digits)
        out.add(n * 1000 if k else n)
    return out


def _mode_ok(value: str, quote: str) -> bool:
    q = quote.lower()
    if value not in _MODE_WORDS or (value != "onsite" and _NEGATED.search(q)):
        return False  # "not a remote role" never reads as remote
    return any(w in q for w in _MODE_WORDS[value])


def _location_ok(value: str, quote: str) -> bool:
    v = geo.norm(value)
    return bool(v) and f" {v} " in f" {geo.norm(quote)} "


def _salary_ok(s: SalaryFact) -> bool:
    q, nums = s.quote.lower(), _numbers(s.quote)
    if s.max is None and s.min is None:
        return False
    if any(v is not None and v not in nums for v in (s.min, s.max)):
        return False
    named = s.currency.lower() in q or any(_SYMBOLS[c] == s.currency for c in _SYMBOLS if c in q)
    return (
        bool(re.fullmatch(r"[A-Z]{3}", s.currency))
        and named
        and any(w in q for w in _PERIOD_WORDS[s.interval])
    )


def checked(job: Job, facts: JobFacts | None) -> dict[str, Any]:
    """The facts that pass the checks, for the blanks this job has: {field: {value, quote}}."""
    if facts is None:
        return {}
    posting, want, out = f"{job.title}\n{job.description}", missing(job), {}
    m, loc, sal = facts.work_mode, facts.location, facts.salary
    if (
        m
        and "work_mode" in want
        and _quoted(m.quote, posting)
        and _mode_ok(m.value.lower(), m.quote)
    ):
        out["work_mode"] = {"value": m.value.lower(), "quote": m.quote}
    if (
        loc
        and "location" in want
        and _quoted(loc.quote, posting)
        and _location_ok(loc.value, loc.quote)
    ):
        out["location"] = {"value": loc.value.strip(), "quote": loc.quote}
    if sal and "salary" in want and _quoted(sal.quote, posting) and _salary_ok(sal):
        out["salary"] = sal.model_dump()
    return out


def fill(job: Job, kept: dict[str, Any]) -> None:
    """Write checked facts into the job's blanks (`checked` already made sure they are blank)."""
    data = {**job.data, "facts": kept}
    if mode := kept.get("work_mode"):
        data["remote"] = mode["value"]
    if loc := kept.get("location"):
        job.location = loc["value"]
    if sal := kept.get("salary"):
        data |= {f"salary_{k}": sal[k] for k in ("min", "max", "currency", "interval")}
    job.data = data
