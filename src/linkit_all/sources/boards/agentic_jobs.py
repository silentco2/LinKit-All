"""Agentic Engineering Jobs (agentic-engineering-jobs.com) over its public, documented REST API:
50 postings a page, body inline. The API allows 30 requests a minute, so pages are spaced a
little over 2 seconds apart. Logic adapted from career-ops (MIT)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, safe_date
from linkit_all.sources.tasks import all_older, feed_task, limited

API = "https://agentic-engineering-jobs.com/api/v1/jobs"
JOB = "https://agentic-engineering-jobs.com/jobs/{}"
PAGE = 50
MAX_PAGES = 40
PAGE_DELAY = 2.1  # seconds: the documented 30 requests / 60 s


class AgenticJobs(Source):
    name = "agentic-jobs"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen = start_page * PAGE
        for page in range(start_page + 1, MAX_PAGES + 1):
            if page > start_page + 1:
                await asyncio.sleep(PAGE_DELAY)
            data = await http.get_json(API, params={"page": page})
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("agentic-jobs: the response carries no data array")
            stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
            yield stubs
            meta = data.get("meta") or {}
            size = meta["per_page"] if isinstance(meta.get("per_page"), int) else PAGE
            seen += len(rows)
            total = meta.get("total")
            if len(rows) < size or (isinstance(total, int) and seen >= total):
                return
            if all_older(stubs, task):
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        title, company = clean(r.get("title")), clean(r.get("companyName"))
        slug = str(r.get("slug") or "").strip()
        if not (title and company and slug):
            return None
        countries = [c for c in r.get("countries") or [] if isinstance(c, str) and c.strip()]
        where = clean(r.get("location")) or ", ".join(countries) or clean(r.get("geoRegion"))
        stub = JobStub(
            source=self.name,
            url=JOB.format(slug),
            title=title,
            company=company,
            location=where,
            description=strip_html(r.get("description") or ""),
            posted_at=safe_date(r.get("postedAt")),
            ats=self.name,
            apply_url=JOB.format(slug),
            remote=remote_from_text(where),
            extra={"id": slug},
        )
        low, high = r.get("salaryMin"), r.get("salaryMax")
        if isinstance(low, int | float) or isinstance(high, int | float):
            stub.salary_min = low if isinstance(low, int | float) else None
            stub.salary_max = high if isinstance(high, int | float) else None
            stub.salary_currency = clean(r.get("salaryCurrency")).upper() or None
            stub.salary_interval = "year"
        return stub
