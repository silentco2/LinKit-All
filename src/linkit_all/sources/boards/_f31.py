"""Helpers private to the F3.1 job boards (the underscore keeps it out of the registry)."""

import html
import re
from collections.abc import Callable
from typing import Any

from linkit_all.sources.ats._f13 import get_page, sitemap_locs
from linkit_all.sources.ats._f16 import ld_stub
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings


def clean(text: Any) -> str:
    """Entities decoded and runs of whitespace collapsed."""
    return " ".join(html.unescape(str(text or "")).split())


def ats_of(apply_url: str | None, default: str) -> str:
    """The ATS behind a board's apply link ("workday", "greenhouse"...), else the board's name."""
    found = detect(apply_url) if apply_url else None
    return found[0] if found else default


async def sitemap_urls(
    http: Http, index_url: str, needle: str, keep: Callable[[str], bool]
) -> list[str]:
    """Posting URLs of the sub-sitemap of `index_url` whose address contains `needle`, in sitemap
    order, de-duplicated, keeping those `keep` accepts."""
    child = next(
        (u for u in sitemap_locs((await get_page(http, index_url)).text) if needle in u), ""
    )
    if not child:
        raise ValueError(f"{index_url} lists no {needle!r} sitemap")
    urls = sitemap_locs((await get_page(http, child)).text)
    return list(dict.fromkeys(u for u in urls if keep(u)))


def board_stub(page: str, *, source: str, url: str, id: str) -> JobStub | None:
    """The page's schema.org JobPosting as a stub; None without a title or an employer name
    (a posting with no company cannot be applied to or de-duplicated)."""
    found = job_postings(page)[:1]
    if not found:
        return None
    posting = found[0]
    org = posting.get("hiringOrganization")
    company = clean(org.get("name") if isinstance(org, dict) else org)
    title = clean(posting.get("title"))
    if not (company and title):
        return None
    stub = ld_stub(
        {**posting, "title": title}, source=source, url=url, company=company, extra={"id": id}
    )
    if stub is None:
        return None
    return stub.model_copy(
        update={"company": company, "remote": stub.remote or remote_from_text(title)}
    )


_ID_TAIL = re.compile(r"[^/?#]+$")


def last_segment(url: str) -> str:
    """The final path segment of a URL (the posting's id or slug)."""
    m = _ID_TAIL.search(url.split("?")[0].split("#")[0].rstrip("/"))
    return m.group(0) if m else ""
