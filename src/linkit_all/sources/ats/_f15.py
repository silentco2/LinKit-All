"""Helpers private to the F1.5 ATS adapters (the underscore keeps it out of the registry): fetch a
posting page and turn its schema.org JobPosting into a stub, and page a long list of postings."""

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime
from typing import Any

from linkit_all.sources.ats._f13 import get_page
from linkit_all.sources.base import JobStub, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import html_to_text

PAGE = 25  # postings per yielded page when every posting costs one request
_PLACEHOLDER = re.compile(r"\bUNAVAILABLE\b,?\s*")  # iCIMS fills unknown address parts with this


async def fetch_html(http: Http, url: str) -> str | None:
    """The page text; None when the site says the page is gone."""
    await http.allowed(url)
    resp = await http.get(url)
    if resp.status_code in (404, 410):
        return None
    resp.raise_for_status()
    return resp.text


def safe_date(value: Any) -> datetime | None:
    """A vendor's datePosted ("2026-06-11 00:00:00", "2026-06-16") as naive UTC; None if odd."""
    try:
        return from_iso(str(value).strip().replace(" ", "T", 1)) if value else None
    except ValueError:
        return None


def _bound(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return number if number > 0 else None


def _salary(p: dict[str, Any]) -> dict[str, Any]:
    """The posting with baseSalary bounds as plain numbers (vendors write "55000.00" or "")."""
    salary = p.get("baseSalary")
    value = salary.get("value") if isinstance(salary, dict) else None
    if not isinstance(value, dict):
        return p
    fixed = {
        **value,
        "minValue": _bound(value.get("minValue")),
        "maxValue": _bound(value.get("maxValue")),
    }
    return {**p, "baseSalary": {**salary, "value": fixed}}  # type: ignore[dict-item]


def posting_stub(
    html: str,
    *,
    source: str,
    url: str,
    board: str,
    id: str,
    company: str,
    escaped: bool = True,
    prep: Callable[[str], str] = str,
) -> JobStub | None:
    """The first JobPosting of `html` as a stub; None when the page has none or no title.
    `company` is the fallback when the posting names no hiring organisation; `escaped` means
    the description is HTML-escaped inside the JSON; `prep` rewrites the raw description."""
    found = job_postings(html)[:1]
    if not found:
        return None
    p = _salary({**found[0], "datePosted": None})
    stub = to_stub(p, source, url, source)
    org = p.get("hiringOrganization")
    org_name = (org.get("name") if isinstance(org, dict) else org) or ""
    location = ", ".join(x for x in _PLACEHOLDER.sub("", stub.location).split(", ") if x)
    if not stub.title:
        return None
    return stub.model_copy(
        update={
            "company": " ".join(str(org_name).split()) or company,
            "location": location,
            "description": html_to_text(prep(str(p.get("description") or "")), escaped=escaped),
            "posted_at": safe_date(found[0].get("datePosted")),
            "remote": stub.remote or remote_from_text(location),
            "extra": {**stub.extra, "board": board, "id": id},
        }
    )


async def paged_postings(
    items: list[str], start_page: int, build: Callable[[str], Awaitable[JobStub | None]]
) -> AsyncIterator[list[JobStub]]:
    """Walk `items` PAGE at a time, yielding what `build` returns for each (None = skip), so a
    long sitemap checkpoints and resumes."""
    for i in range(start_page * PAGE, len(items), PAGE):
        yield [s for item in items[i : i + PAGE] if (s := await build(item))]


__all__ = ["PAGE", "fetch_html", "get_page", "paged_postings", "posting_stub", "safe_date"]
