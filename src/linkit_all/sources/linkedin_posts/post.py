"""One LinkedIn post as scraped, plus the small text helpers around it (age, emails, links)."""

# ruff: noqa: RUF001  (Arabic time words are the point here)

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

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
    posted_text: str  # relative time label as shown ("3d", "1w")
    text: str  # full post text
    links: tuple[str, ...]  # external hrefs (lnkd.in kept as is)
    emails: tuple[str, ...]
    scraped_at: datetime


_AGE = re.compile(r"(\d+)\s*([^\W\d_]+)")
_NOW = re.compile(r"\bnow\b|الان")


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


def posted_at(post: RawPost) -> datetime | None:
    """When the post went up, from its relative label and `scraped_at` (None if unreadable)."""
    label = post.posted_text.translate(_DIGITS)
    if (m := _AGE.search(label)) is not None:
        delta = _delta(int(m.group(1)), m.group(2))
        if delta is not None:
            return post.scraped_at - delta
    if _NOW.search(_MARKS.sub("", label.translate(_LETTERS)).lower()):
        return post.scraped_at
    return None


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
