"""Knock-out pre-scan: form questions an honest answer to which gets the application rejected
automatically (minimum years, a required degree, no sponsorship offered, a pay ceiling below the
user's expectation). Rules only, profile and CV only, no AI; the job parks so the user decides
before an application is spent. A wrong hit costs one click, so every rule fires only on a
stated requirement and known profile data. Logic adapted from career-ops (MIT)."""

import re
from dataclasses import dataclass
from typing import Literal

from linkit_all.apply.answers import (
    Context,
    Question,
    sensitive_answer,
    sensitive_category,
    yes_no,
)

Kind = Literal["years", "degree", "sponsorship", "work_authorization", "salary"]


@dataclass(frozen=True)
class Knockout:
    question: Question
    kind: Kind
    yours: str  # what the profile or CV says, for the Needs you card

    @property
    def reason(self) -> str:
        return f'This form would reject you: it asks "{self.question.label.strip()}" ({self.yours})'


_YES_NO = re.compile(r"^\s*(yes|no|نعم|لا)\b", re.I)
_YEARS = re.compile(
    r"(?P<more>more than|over|أكثر من)?\s*(?P<n>\d{1,2})\s*\+?\s*(?:or more\s+)?"
    r"(?:years?|yrs?|سنوات|سنة|سنين)",
    re.I,
)
_EXPERIENCE = re.compile(r"experience|خبرة", re.I)

_LEVELS: list[tuple[int, re.Pattern[str]]] = [
    (3, re.compile(r"ph\.?\s?d\b|doctorate|doctoral|دكتوراه", re.I)),
    (2, re.compile(r"master|m\.sc\b|msc\b|\bmba\b|ماجستير", re.I)),
    (1, re.compile(r"bachelor|b\.sc\b|bsc\b|undergraduate degree|بكالوريوس|ليسانس", re.I)),
]
_LEVEL_NAMES = {1: "a Bachelor's degree", 2: "a Master's degree", 3: "a doctorate"}
_HAVE_DEGREE = re.compile(
    r"do you (?:currently )?(?:have|hold|possess)|have you (?:completed|obtained|earned)"
    r"|هل (?:لديك|تحمل)",
    re.I,
)
_OR_EQUIVALENT = re.compile(r"or equivalent|or related experience|أو ما يعادل", re.I)

_NO_SPONSORSHIP = re.compile(
    r"(?:not|unable to|cannot|can ?not|won't|will not|do(?:es)? not|don't) (?:be able to )?"
    r"(?:offer|provide|support)?\s*(?:visa |work[- ]permit |employment )?sponsor"
    r"|no (?:visa |work[- ]permit )?sponsorship"
    r"|without (?:the need for )?(?:visa |employer )?sponsorship"
    r"|sponsorship is not (?:available|offered|provided)",
    re.I,
)

_MONEY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k\b)?", re.I)
_SALARY_OK = re.compile(
    r"comfortable|acceptable|accept|within|meets?|align|agree|fit|okay|suit|مناسب|يناسب", re.I
)
_PAY = re.compile(r"salary|compensation|pay\b|range\b|remuneration|راتب|الأجر", re.I)
_CURRENCY = re.compile(r"\b(USD|EUR|GBP|EGP|AED|SAR|QAR|KWD|CAD|AUD|INR)\b")


def _is_yes_no(q: Question) -> bool:
    if q.kind in ("yesno", "checkbox"):
        return True
    if q.kind not in ("radio", "select", "combobox"):
        return False
    return 2 <= len(q.options) <= 3 and sum(bool(_YES_NO.match(o)) for o in q.options) >= 2


def _text(q: Question) -> str:
    return f"{q.label} {q.description}"


def _years(q: Question, ctx: Context) -> Knockout | None:
    have = ctx.answers.years_experience
    if have is None or not _is_yes_no(q) or not _EXPERIENCE.search(q.label):
        return None
    if (m := _YEARS.search(q.label)) is None:
        return None
    need = int(m["n"]) + (1 if m["more"] else 0)
    if have >= need:
        return None
    return Knockout(q, "years", f"your profile says {have} years")


def degree_level(text: str) -> int:
    """Highest degree level named in `text`: 3 doctorate, 2 Master's, 1 Bachelor's, 0 none."""
    return next((level for level, rx in _LEVELS if rx.search(text)), 0)


def _degree(q: Question, cv: str) -> Knockout | None:
    if not _is_yes_no(q) or not _HAVE_DEGREE.search(q.label) or _OR_EQUIVALENT.search(_text(q)):
        return None
    need, have = degree_level(q.label), degree_level(cv)
    # A CV that names no degree at all says nothing: the question is left to the usual flow.
    if not need or not have or have >= need:
        return None
    return Knockout(q, "degree", f"your CV shows {_LEVEL_NAMES[have]}")


def _sponsorship(q: Question, ctx: Context, job_text: str) -> Knockout | None:
    """Needing a visa is normal for a job abroad, so it knocks out only where the form or the
    posting says the employer does not sponsor."""
    category = sensitive_category(q)
    if category not in ("sponsorship", "work_authorization"):
        return None
    if not _NO_SPONSORSHIP.search(f"{_text(q)} {job_text}"):
        return None
    value, _ = sensitive_answer(q, category, ctx)
    if value is None:
        return None
    bad = yes_no(q, category == "sponsorship")  # needing sponsorship / not being authorized
    if bad is None or value != bad or value == yes_no(q, category != "sponsorship"):
        return None
    yours = (
        "you would need sponsorship and this employer offers none"
        if category == "sponsorship"
        else "you are not authorized to work there and this employer does not sponsor"
    )
    return Knockout(q, category, yours)  # type: ignore[arg-type]


def _amounts(text: str) -> list[float]:
    out = []
    for digits, k in _MONEY.findall(text):
        n = float(digits.replace(",", "")) * (1000 if k else 1)
        if n >= 100:  # skips "40 hours", "2 weeks"
            out.append(n)
    return out


def _salary(q: Question, ctx: Context) -> Knockout | None:
    a = ctx.answers
    if not _is_yes_no(q) or not _PAY.search(q.label) or not _SALARY_OK.search(q.label):
        return None
    want = _amounts(a.salary_expectation)
    offered = _amounts(q.label)
    if not want or not offered:
        return None
    named = _CURRENCY.search(q.label)
    if named and a.salary_currency and named[1] != a.salary_currency.upper():
        return None
    top = max(offered)
    # Six times apart is a monthly figure against a yearly one, not a mismatch.
    if want[0] <= top or want[0] / top >= 6:
        return None
    return Knockout(q, "salary", f"you expect {a.salary_expectation} {a.salary_currency}".strip())


def find(
    questions: list[Question], ctx: Context, cv: str = "", job_text: str = ""
) -> list[Knockout]:
    """Every question of this page that would reject the user, in form order."""
    hits = []
    for q in questions:
        hit = _years(q, ctx) or _degree(q, cv) or _sponsorship(q, ctx, job_text) or _salary(q, ctx)
        if hit:
            hits.append(hit)
    return hits
