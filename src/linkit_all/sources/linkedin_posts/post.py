"""One LinkedIn post as read from its public page, plus its text helpers (emails, links)."""

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import from_iso
from linkit_all.sources.posts import find_emails, find_links

__all__ = ["RawPost", "find_emails", "find_links", "read_post"]


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
