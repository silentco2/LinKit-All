"""Kalibrr (kalibrr.com), a Southeast Asian job board whose postings each name their employer.
Reads the public JSON search the site's own job board calls, one request per query and country.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import query_tasks
from linkit_all.sources.aggregators._keyed import split_location
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

API = "https://www.kalibrr.com/kjs/job_board/search"
POSTING = "https://www.kalibrr.com/c/{}/jobs/{}/{}"
MARKETS = {"id": "Indonesia", "ph": "Philippines"}  # ISO code -> the site's country name
MAX_ROWS = 2000  # one request reads the lot: offset paging under relevance sort repeats rows
SHORTENERS = {"bit.ly", "forms.gle", "goo.gl", "lnkd.in", "s.id", "t.co", "tinyurl.com"}
INTERVALS = {"hour", "day", "month", "year"}
_SAFE = re.compile(r"^[\w-]+$")


class Kalibrr(Source):
    name = "kalibrr"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [t for t in query_tasks(self.name, cfg) if split_location(t.location)[0] in MARKETS]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        code, _ = split_location(task.location)
        country = MARKETS.get(code or "")
        if start_page or not country:
            return
        params = {"country": country, "text": task.query, "limit": min(task.limit, MAX_ROWS)}
        data = await http.get_json(API, params=params | {"offset": 0})
        # An unknown country is ignored by the search, which answers another market: keep only
        # rows that really sit in the one asked for.
        rows = [r for r in data.get("jobs") or [] if self.country(r).lower() == country.lower()]
        links: dict[str, int] = {}
        for r in rows:
            if link := self.apply_link(r):
                links[link] = links.get(link, 0) + 1
        seen: set[int] = set()
        stubs = []
        for r in rows:
            if r.get("id") not in seen and (s := self.stub(r, links)):
                seen.add(r["id"])
                stubs.append(s)
        if stubs:
            yield stubs

    @staticmethod
    def country(row: dict[str, Any]) -> str:
        address = (row.get("google_location") or {}).get("address_components") or {}
        return (address.get("country") or "").strip()

    @staticmethod
    def apply_link(row: dict[str, Any]) -> str:
        """The posting's own external apply link, unless it goes through a redirector."""
        raw = (row.get("apply_redirect_url") or "").strip()
        parts = urlsplit(raw)
        if parts.scheme not in ("http", "https") or (parts.hostname or "").lower() in SHORTENERS:
            return ""
        return raw

    def stub(self, r: dict[str, Any], links: dict[str, int]) -> JobStub | None:
        company = (r.get("company_name") or (r.get("company") or {}).get("name") or "").strip()
        code, slug = (r.get("company") or {}).get("code") or "", r.get("slug") or ""
        title = " ".join((r.get("name") or "").split())
        if not (r.get("id") and title and company and _SAFE.match(code) and _SAFE.match(slug)):
            return None
        url = POSTING.format(code, r["id"], slug)
        link = self.apply_link(r)
        address = (r.get("google_location") or {}).get("address_components") or {}
        place = [(address.get(k) or "").strip() for k in ("city", "region", "country")]
        remote: Remote | None = (
            "remote" if r.get("is_work_from_home") else "hybrid" if r.get("is_hybrid") else None
        )
        body = f"{r.get('description') or ''}\n{r.get('qualifications') or ''}"
        stub = JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=", ".join(dict.fromkeys(p for p in place if p)),
            description=strip_html(body),
            posted_at=from_iso(r.get("activation_date")),
            ats=self.name,
            # a link several postings share is an intake form, not this posting's own page
            apply_url=link if link and links.get(link) == 1 else url,
            remote=remote,
            extra={"id": r["id"]},
        )
        currency = (r.get("salary_currency") or "").strip().upper()
        if r.get("salary_shown") and r.get("salary_interval") in INTERVALS and len(currency) == 3:
            low, high = r.get("base_salary"), r.get("maximum_salary")
            if low or high:  # a hidden salary still carries figures: only shown ones are used
                stub.salary_min, stub.salary_max = low, high
                stub.salary_currency, stub.salary_interval = currency, r["salary_interval"]
        return stub
