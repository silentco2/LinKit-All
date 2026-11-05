"""One LinkedIn post as read from its public page, plus its text helpers (emails, links)."""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import from_iso


@dataclass(frozen=True)
class RawPost:
    urn: str  # "urn:li:activity:<id>", the dedupe key
    url: str  # https://www.linkedin.com/posts/<slug>-activity-<id>-<xxxx>
    author: str
    author_url: str | None  # profile or company page
    headline: str  # author headline ("HR at Acme"); the public page does not give it
    posted_at: datetime | None  # naive UTC
    text: str  # full post text
    links: tuple[str, ...]  # external hrefs (lnkd.in kept as is)
    emails: tuple[str, ...]
    scraped_at: datetime


def _posting(html: str) -> dict[str, Any] | None:
    for script in LexborHTMLParser(html).css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "SocialMediaPosting":
                return item
    return None


def read_post(html: str, url: str, urn: str, scraped_at: datetime) -> RawPost | None:
    """The post on a public post page, from its JSON-LD. Only the post itself is read: the
    comments on the page hold other people's emails and phone numbers."""
    item = _posting(html) or {}
    text = item.get("articleBody")
    if not isinstance(text, str) or not text.strip():
        return None
    author = item.get("author")
    author = author if isinstance(author, dict) else {}
    try:
        posted = from_iso(item.get("datePublished"))
    except (TypeError, ValueError):
        posted = None
    return RawPost(
        urn=urn,
        url=url,
        author=str(author.get("name") or ""),
        author_url=author.get("url") if isinstance(author.get("url"), str) else None,
        headline="",
        posted_at=posted,
        text=text.strip(),
        links=find_links(text),
        emails=find_emails(text),
        scraped_at=scraped_at,
    )


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
