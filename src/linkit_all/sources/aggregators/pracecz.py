"""prace.cz, a Czech job portal (Alma Career). Keyword search over the public /nabidky/
listing pages, 40 a page. The page is Next.js app-router output: its data stream carries
`totalItems` and `currentPageItems` as JSON, read instead of the HTML (whose class names change
on every build). A posting with a jobs.cz career page uses that page as its address. Pay is
kept as the site states it, never annualised. Logic adapted from career-ops (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote, urlsplit

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import bracket_slice, clean, decode_flight, safe_date
from linkit_all.sources.tasks import limited, query_tasks

SEARCH = "https://www.prace.cz/nabidky/"
JOB = "https://www.prace.cz/nabidka/{}/"
PAGE = 40
MAX_PAGES = 10
_PERIODS = {"MONTH": "month", "YEAR": "year", "HOUR": "hour"}
_TOTAL = re.compile(r'"totalItems":(\d+)')


def results(html: str) -> tuple[int, list[dict[str, Any]]]:
    """(totalItems, currentPageItems) from the page's Next.js data stream."""
    flight = decode_flight(html)
    total = _TOTAL.search(flight)
    items = bracket_slice(flight, '"currentPageItems":', "[", "]")
    if total is None or items is None:
        raise ValueError("pracecz: no currentPageItems/totalItems (markup changed?)")
    return int(total[1]), [x for x in json.loads(items) if isinstance(x, dict)]


class PraceCz(Source):
    name = "pracecz"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = f"{SEARCH}?q={quote(task.query)}" + (f"&page={page}" if page > 1 else "")
            total, items = results((await get_page(http, url)).text)
            if not items:
                return
            yield [s for it in items if (s := self.stub(it))]
            if page * PAGE >= total:
                return

    def stub(self, it: dict[str, Any]) -> JobStub | None:
        advert, meta = it.get("advert") or {}, it.get("metadata") or {}
        title, jid = clean(advert.get("title")), str(meta.get("advertId") or "").strip()
        company = clean((it.get("company") or {}).get("publicName"))
        if not (title and jid and company):
            return None
        career = str(((it.get("extended") or {}).get("careerPage") or {}).get("url") or "")
        parts = urlsplit(career)
        own = (
            f"https://{parts.hostname}{parts.path}"
            if parts.scheme == "https" and (parts.hostname or "").endswith(".jobs.cz")
            else JOB.format(quote(jid, safe=""))
        )
        work = advert.get("workLocation") or {}
        cities = [clean(p.get("city")) for p in work.get("places") or [] if isinstance(p, dict)]
        remote = work.get("type") == "FULL_REMOTE"
        stub = JobStub(
            source=self.name,
            url=own,
            title=title,
            company=company,
            location=", ".join(c for c in (["Remote"] if remote else []) + cities if c),
            posted_at=safe_date(meta.get("publishedAt")),
            ats=self.name,
            apply_url=own,
            remote="remote" if remote else None,
            extra={"id": jid, "language": advert.get("language")},
        )
        pay = advert.get("salary") or {}
        period = _PERIODS.get(str(pay.get("period") or ""))
        low, high = (
            v if isinstance(v, int | float) and v > 0 else None
            for v in (pay.get("min"), pay.get("max"))
        )
        if period and pay.get("displayMode") != "NO" and (low or high):
            stub.salary_min, stub.salary_max, stub.salary_interval = low, high, period
            stub.salary_currency = clean(pay.get("currency")).upper() or None
        return stub
