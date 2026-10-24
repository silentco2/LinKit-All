"""Small helpers private to the F1.6 adapters (the underscore keeps it out of the registry)."""

import json
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from typing import Any, TypeVar
from urllib.parse import urljoin

import httpx
from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f13 import get_page
from linkit_all.sources.base import JobStub, from_iso, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.jsonld import to_stub

T = TypeVar("T")
# Failures that cost one posting, not the board: refused, an HTTP error, or 429/5xx after retries.
GONE = (Unsupported, httpx.HTTPError, RetryableStatus)
CHUNK = 20  # postings per page: their detail fetches run together (Http paces them per host)


def chunks(items: Sequence[T], start_page: int, size: int = CHUNK) -> Iterator[Sequence[T]]:
    """`items` in pages of `size`, from page `start_page` (a checkpointed run resumes there)."""
    for i in range(start_page * size, len(items), size):
        yield items[i : i + size]


def next_data(html: str) -> dict[str, Any] | None:
    """The `__NEXT_DATA__` JSON of a Next.js page, or None when it is missing or not JSON."""
    node = LexborHTMLParser(html).css_first("script#__NEXT_DATA__")
    try:
        data = json.loads(node.text(deep=True)) if node else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def links(html: str, base: str, keep: Callable[[str], bool]) -> list[str]:
    """Absolute, de-duplicated hrefs of the anchors whose raw href passes `keep`, in page order
    (a job card often links the same posting twice)."""
    found: dict[str, None] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if href and keep(href):
            found[urljoin(base, href).split("#")[0]] = None
    return list(found)


async def page_text(http: Http, url: str) -> str | None:
    """GET of one detail page; None when it is gone, refused or unreadable, so
    one bad posting never stops the board."""
    try:
        return (await get_page(http, url)).text
    except GONE:
        return None


def when(value: Any) -> datetime | None:
    """A posting date ("2026-07-14T13:34:41+00:00", "2026-07-01", "2026-07-01 10:00:00") as naive
    UTC; None when it is missing, unreadable or in the future (a vendor's placeholder)."""
    try:
        dt = from_iso(value.strip()) if isinstance(value, str) else None
    except ValueError:
        return None
    return dt if dt and dt <= datetime.now(UTC).replace(tzinfo=None) else None


def ld_stub(
    posting: dict[str, Any],
    *,
    source: str,
    url: str,
    company: str,
    extra: dict[str, Any],
    escaped: bool = False,
) -> JobStub | None:
    """A schema.org JobPosting as a stub (None when it has no title). `company` is used when
    the posting names none; `escaped`: the vendor HTML-escapes the description markup."""
    stub = to_stub({**posting, "datePosted": None}, source, url, source)
    if not stub.title:
        return None
    org = posting.get("hiringOrganization")
    named = stub.company if isinstance(org, dict) and org.get("name") else company
    return stub.model_copy(
        update={
            "company": named,
            "description": strip_html(posting.get("description") or "", escaped=escaped),
            "posted_at": when(posting.get("datePosted")),
            "remote": stub.remote or remote_from_text(stub.location),
            "extra": {**stub.extra, **extra},
        }
    )
