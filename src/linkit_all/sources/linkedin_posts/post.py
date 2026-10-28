"""One LinkedIn post as scraped, plus the small text helpers around it (age, emails, links)."""

# ruff: noqa: RUF001  (Arabic time words are the point here)

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

# Arabic-Indic and Persian digits -> ASCII
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_MARKS = re.compile("[ؐ-ًؚ-ٰٟـ]")  # Arabic diacritics, tatweel
_LETTERS = str.maketrans("أإآٱةىئؤ", "ااااهييو")


@dataclass(frozen=True)
class RawPost:
    urn: str  # "urn:li:activity:<id>", the dedupe key
    url: str  # https://www.linkedin.com/feed/update/<urn>/
    author: str
    author_url: str | None  # profile or company page
    headline: str  # author headline ("HR at Acme")
    posted_text: str  # time label as shown ("3d", "Yesterday", "Oct 22")
    text: str  # full post text
    links: tuple[str, ...]  # external hrefs (lnkd.in kept as is)
    emails: tuple[str, ...]
    scraped_at: datetime


_AGE = re.compile(r"(\d+)\s*([^\W\d_]+)")
_NOW = re.compile(r"\bnow\b|الان")
_YESTERDAY = re.compile(r"\byesterday\b|امس")
# "Oct 22", "22 Oct", "Oct 22, 2025", "22 اكتوبر" (after _LETTERS, so أكتوبر -> اكتوبر)
_DATE = re.compile(r"(?:(\d{1,2})\s+([^\W\d_]+)|([^\W\d_]+)\s+(\d{1,2}))(?:,?\s+(\d{4}))?")
_EN_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
# ponytail: Egyptian month names; Levantine ones (تشرين...) are not read
_AR_MONTHS = ("يناير", "فبراير", "مارس", "ابريل", "مايو", "يونيو", "يوليو", "اغسطس", "سبتمبر",
              "اكتوبر", "نوفمبر", "ديسمبر")  # fmt: skip


def _delta(count: int, unit: str) -> timedelta | None:
    """The age a count plus unit ("d", "days", "أيام", "ي") stands for."""
    u = _MARKS.sub("", unit.translate(_LETTERS)).lower()
    if u.startswith(("mo", "شهر", "اشهر")) or u == "ش":
        return timedelta(days=30 * count)
    if u.startswith(("mi", "دقي", "دقائق")) or u in ("m", "د"):
        return timedelta(minutes=count)
    if u.startswith(("h", "ساع")) or u == "س":
        return timedelta(hours=count)
    if u.startswith(("d", "يوم", "ايام")) or u == "ي":
        return timedelta(days=count)
    if u.startswith(("w", "اسب")) or u == "ا":
        return timedelta(weeks=count)
    if u.startswith(("y", "سن", "عام")):
        return timedelta(days=365 * count)
    return None


def _month(word: str) -> int | None:
    w = word.lower()
    if len(w) >= 3 and w[:3] in _EN_MONTHS:
        return _EN_MONTHS.index(w[:3]) + 1
    return _AR_MONTHS.index(w) + 1 if w in _AR_MONTHS else None


def _dated(label: str, scraped_at: datetime) -> datetime | None:
    """Midnight of an absolute "Oct 22" style label; a date without a year that would lie in
    the future is last year's."""
    for m in _DATE.finditer(label):
        day, word = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        if (month := _month(word)) is None:
            continue
        year = int(m.group(5) or scraped_at.year)
        try:
            at = scraped_at.replace(year=year, month=month, day=int(day), hour=0, minute=0,
                                    second=0, microsecond=0)  # fmt: skip
            if m.group(5) is None and at > scraped_at:
                at = at.replace(year=year - 1)
        except ValueError:  # Feb 30, or Feb 29 moved to a non-leap year
            return None
        return at
    return None


def posted_at(post: RawPost) -> datetime | None:
    """When the post went up, from its label ("3d", "Yesterday", "Oct 22") and `scraped_at`
    (None if unreadable)."""
    label = _MARKS.sub("", post.posted_text.translate(_DIGITS).translate(_LETTERS))
    if (at := _dated(label, post.scraped_at)) is not None:  # first: "22 Dec" is not 22 days
        return at
    if _YESTERDAY.search(label.lower()):
        return post.scraped_at - timedelta(days=1)
    if (m := _AGE.search(label)) is not None:
        delta = _delta(int(m.group(1)), m.group(2))
        if delta is not None:
            return post.scraped_at - delta
    if _NOW.search(label.lower()):
        return post.scraped_at
    return None


# ponytail: LinkedIn shows no result total, so "more than 100" is counted on what was scraped
RECENT_AFTER = 100
WINDOW_DAYS = {"day": 1, "week": 7}


def keep_recent(
    posts: Sequence[RawPost], window: Literal["day", "week"], after: int = RECENT_AFTER
) -> list[RawPost]:
    """All posts while there are at most `after`; past that, only those posted within `window`
    (calendar days). A post whose date cannot be read is kept: nothing is dropped on a guess."""
    if len(posts) <= after:
        return list(posts)
    days = WINDOW_DAYS[window]
    return [
        p
        for p in posts
        if (at := posted_at(p)) is None or (p.scraped_at.date() - at.date()).days <= days
    ]


_EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_ASSET_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "ico", "css", "js", "pdf", "mp4"}
_URL = re.compile(
    r"(?:https?://|(?<![\w@./-])(?:www\.|lnkd\.in/|bit\.ly/))[^\s<>\"'؀-ۿ]+",
    re.IGNORECASE,
)
_TRAIL = ".,;:!?)]}>»'\"…"


def find_emails(text: str) -> tuple[str, ...]:
    """Distinct, lower-cased addresses in order of appearance. Trailing punctuation is not part
    of an address; `logo@2x.png` style asset names are not addresses."""
    found: dict[str, None] = {}
    for m in _EMAIL.finditer(text):
        mail = m.group(0).rstrip(_TRAIL).lower()
        domain = mail.partition("@")[2]
        if domain.rsplit(".", 1)[-1] in _ASSET_TLDS or re.fullmatch(r"\d+x", domain.split(".")[0]):
            continue
        found[mail] = None
    return tuple(found)


def find_links(text: str) -> tuple[str, ...]:
    """Distinct URLs in order of appearance (scheme added to bare www., lnkd.in/, bit.ly/)."""
    found: dict[str, None] = {}
    for m in _URL.finditer(text):
        url = m.group(0).rstrip(_TRAIL)
        if not url.lower().startswith("http"):
            url = "https://" + url
        found[url] = None
    return tuple(found)
