"""The closing date a job description states, so jobs about to close are applied to first.

Rules only: a cue ("closes", "deadline", "apply by", "آخر موعد") followed closely by a date.
A date with no year is read as its next occurrence. A wrong reading only changes the order
jobs are applied in, never whether they are.

Logic adapted from career-ops (MIT).
"""

import re
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import Protocol, TypeVar

SOON_DAYS = 3

_NAMES = [
    ("jan", "january", "يناير"), ("feb", "february", "فبراير"), ("mar", "march", "مارس"),
    ("apr", "april", "أبريل"), ("may", "مايو"), ("jun", "june", "يونيو"),
    ("jul", "july", "يوليو"), ("aug", "august", "أغسطس"), ("sep", "sept", "september", "سبتمبر"),
    ("oct", "october", "أكتوبر"), ("nov", "november", "نوفمبر"), ("dec", "december", "ديسمبر"),
]  # fmt: skip
_MONTHS = {name: n for n, names in enumerate(_NAMES, 1) for name in names}
_MONTH = "|".join(sorted(_MONTHS, key=len, reverse=True))
_DAY = r"(?P<d>\d{1,2})(?:st|nd|rd|th)?"
_YEAR = r",?(?:\s+(?P<y>\d{4}))?"
_CUE = re.compile(
    r"\b(?:clos(?:es|ing|e)|deadline|apply (?:by|before)|applications? (?:due|accepted until|"
    r"received by|must be received by)|last (?:date|day)|valid (?:until|till))\b"
    r"|آخر موعد|اخر موعد|ينتهي التقديم|تاريخ الإغلاق",
    re.I,
)
_DATES = [
    re.compile(r"(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})"),
    re.compile(r"(?P<a>\d{1,2})[/.](?P<b>\d{1,2})[/.](?P<y>\d{4})"),
    re.compile(rf"{_DAY}\s+(?:of\s+)?(?P<mon>{_MONTH})\.?{_YEAR}", re.I),
    re.compile(rf"(?P<mon>{_MONTH})\.?\s+{_DAY}\b{_YEAR}", re.I),
]
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_REACH = 40  # characters after the cue in which the date must start


class _HasDescription(Protocol):
    @property
    def description(self) -> str: ...


_J = TypeVar("_J", bound=_HasDescription)


def _read(m: re.Match[str], today: date) -> date | None:
    g = m.groupdict()
    if "a" in g:  # 20/11/2026 is day first; 11/20/2026 can only be month first
        a, b = int(g["a"]), int(g["b"])
        day, month = (b, a) if b > 12 else (a, b)
    else:
        day = int(g["d"])
        month = int(g["m"]) if "m" in g else _MONTHS[g["mon"].lower()]
    try:
        if g.get("y"):
            return date(int(g["y"]), month, day)
        found = date(today.year, month, day)
        # No year: a date well behind today means next year's.
        return found if found >= today - timedelta(days=30) else date(today.year + 1, month, day)
    except ValueError:
        return None


def closing_date(text: str, today: date) -> date | None:
    """The earliest closing date the text states, or None."""
    text = text.translate(_AR_DIGITS)
    found = []
    for cue in _CUE.finditer(text):
        window = text[cue.end() : cue.end() + _REACH + 30]
        hits = [m for p in _DATES if (m := p.search(window)) and m.start() <= _REACH]
        if hits and (when := _read(min(hits, key=lambda m: m.start()), today)):
            found.append(when)
    return min(found, default=None)


def closes_soon(text: str, now: datetime, days: int = SOON_DAYS) -> bool:
    """The posting closes today or within `days` days (a date already past is not urgent)."""
    when = closing_date(text, now.date())
    return when is not None and 0 <= (when - now.date()).days <= days


def deadline_first(jobs: Sequence[_J], now: datetime) -> list[_J]:
    """The same jobs, those closing within `SOON_DAYS` first; the order is otherwise kept."""
    return sorted(jobs, key=lambda j: not closes_soon(j.description, now))
