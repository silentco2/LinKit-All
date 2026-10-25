"""ITviec (itviec.com), Vietnam's IT-only job board: the listing pages carry each posting's key and
slug, the posting page a schema.org JobPosting. Logic adapted from freehire (MIT)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.ats._f15 import fetch_html
from linkit_all.sources.ats._f16 import ld_stub
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.boards._f31 import clean
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.text import html_to_text

LIST_URL = "https://itviec.com/it-jobs"
MAX_PAGES = 100  # three times the measured catalogue
_MODES: dict[str, Remote] = {"At office": "onsite", "Hybrid": "hybrid", "Remote": "remote"}
_HEADINGS = {
    "Top 3 Reasons To Join Us", "The Job", "Your Skills and Experience",
    "Why You'll Love Working Here",
}  # fmt: skip


def parse_cards(page: str) -> list[tuple[str, str]]:
    """(card key, posting URL) of every job card on a listing page."""
    out = []
    for node in LexborHTMLParser(page).css("[data-job-key]"):
        slug = (node.attributes.get("data-search--job-selection-job-slug-value") or "").strip()
        key = (node.attributes.get("data-job-key") or "").strip()
        if slug and key:
            out.append((key, f"{LIST_URL}/{quote(slug)}"))
    return out


def description_html(raw: str) -> str:
    """The posting's description: known section headings and bare lines become markup."""
    parts = []
    for line in (ln.strip() for ln in raw.split("\n")):
        if not line:
            continue
        if line in _HEADINGS:
            parts.append(f"<h3>{line}</h3>")
        elif line.startswith("<"):
            parts.append(line)
        else:
            parts.append(f"<p>{line}</p>")
    return "".join(parts)


def work_mode(page: str) -> Remote | None:
    """The one work mode the header states (several, or none, say nothing)."""
    modes = {
        _MODES[t]
        for n in LexborHTMLParser(page).css(".preview-header-item")
        if (t := clean(n.text(deep=True))) in _MODES
    }
    return modes.pop() if len(modes) == 1 else None


def location_of(posting: dict[str, Any]) -> str:
    """Cities (the region field; the locality is often "Not Available") plus the country."""
    places = posting.get("jobLocation") or []
    places = places if isinstance(places, list) else [places]
    cities: list[str] = []
    for place in places:
        addr = (place or {}).get("address") or {}
        city = clean(addr.get("addressRegion"))
        locality = clean(addr.get("addressLocality"))
        city = city or ("" if locality.lower() == "not available" else locality)
        if city and city not in cities:
            cities.append(city)
    countries = {clean((p or {}).get("address", {}).get("addressCountry")) for p in places}
    if countries == {"VN"}:
        cities.append("Vietnam")
    return ", ".join(cities)


class ITviec(Source):
    name = "itviec"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()
        count = 0
        for page in range(1, MAX_PAGES + 1):
            await http.allowed(LIST_URL)
            resp = await http.get(LIST_URL, params={"page": page} if page > 1 else None)
            resp.raise_for_status()
            new = [(k, u) for k, u in parse_cards(resp.text) if u not in seen]
            if not new:
                return  # past the last page, or a changed layout
            seen.update(u for _, u in new)
            if page - 1 >= start_page:  # resume: skipped pages are re-read
                built = await asyncio.gather(*(self.build(http, k, u) for k, u in new))
                stubs = [s for s in built if s][: task.limit - count]
                count += len(stubs)
                yield stubs
                if count >= task.limit:
                    return

    async def build(self, http: Http, key: str, url: str) -> JobStub | None:
        page = await fetch_html(http, url)
        found = job_postings(page or "")[:1]
        if not (page and found):
            return None
        posting = found[0]
        h1 = LexborHTMLParser(page).css_first("h1")
        title = clean(h1.text(deep=True)) if h1 is not None else clean(posting.get("title"))
        org = posting.get("hiringOrganization")
        company = clean(org.get("name") if isinstance(org, dict) else org)
        body = html_to_text(description_html(str(posting.get("description") or "")))
        if not (title and company and body):
            return None
        stub = ld_stub(
            {**posting, "title": title, "description": ""},
            source=self.name, url=url, company=company, extra={"id": key},
        )  # fmt: skip
        if stub is None:
            return None
        lo, hi = _bound(posting, "minValue"), _bound(posting, "maxValue")
        cur = str(((posting.get("baseSalary") or {}).get("currency")) or "").upper()
        unit = _unit(posting)
        paid = bool(lo or hi) and len(cur) == 3 and unit
        return stub.model_copy(
            update={
                "title": title,
                "company": company,
                "location": location_of(posting),
                "description": body,
                "remote": work_mode(page),
                "salary_min": lo if paid else None,
                "salary_max": hi if paid else None,
                "salary_currency": cur if paid else None,
                "salary_interval": unit if paid else None,
                "extra": {**stub.extra, "skills": clean(posting.get("skills"))},
            }
        )


def _value(posting: dict[str, Any]) -> dict[str, Any]:
    value = (posting.get("baseSalary") or {}).get("value")
    return value if isinstance(value, dict) else {}


def _bound(posting: dict[str, Any], key: str) -> float | None:
    try:
        n = float(_value(posting).get(key) or "")
    except (TypeError, ValueError):
        return None
    return round(n) if n > 0 else None


def _unit(posting: dict[str, Any]) -> str | None:
    unit = str(_value(posting).get("unitText") or "").lower()
    return unit if unit in ("hour", "day", "month", "year") else None
