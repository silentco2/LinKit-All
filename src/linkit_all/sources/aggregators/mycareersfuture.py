"""MyCareersFuture (mycareersfuture.gov.sg), the Singapore government job portal. The v2 jobs API
carries every body inline and pages newest first. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from math import ceil
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.tasks import all_older, query_tasks

API = "https://api.mycareersfuture.gov.sg/v2/jobs"
JOB_URL = "https://www.mycareersfuture.gov.sg/job/{}"
PAGE = 100
INTERVALS = {
    "hourly": "hour", "daily": "day", "weekly": "week", "monthly": "month",
    "annually": "year", "annual": "year", "yearly": "year",
}  # fmt: skip


class MyCareersFuture(Source):
    name = "mycareersfuture"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page, ceil(task.limit / PAGE)):
            params = {
                "limit": PAGE,
                "page": page,
                "search": task.query,
                "sortBy": "new_posting_date",
            }
            try:
                data = await http.get_json(API, params=params)
            except (httpx.HTTPError, RetryableStatus):
                if page == start_page:
                    raise
                return  # the portal rate-limits a long sweep partway: keep what was gathered
            rows = data.get("results") or []
            stubs = [s for r in rows if (s := self.stub(r))]
            if stubs:
                yield stubs
            if len(rows) < PAGE or all_older(stubs, task):
                return

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        # an agency posts for its client: the hiring company is the real employer
        company = ((p.get("hiringCompany") or {}).get("name") or "").strip() or (
            (p.get("postedCompany") or {}).get("name") or ""
        ).strip()
        if not p.get("uuid") or not company or not p.get("title"):
            return None
        address = p.get("address") or {}
        overseas = address.get("isOverseas") and address.get("overseasCountry")
        url = JOB_URL.format(p["uuid"])
        stub = JobStub(
            source=self.name,
            url=url,
            title=p["title"].strip(),
            company=company,
            location=overseas or "Singapore",
            description=strip_html(p.get("description") or ""),
            posted_at=from_iso((p.get("metadata") or {}).get("newPostingDate")),
            ats=self.name,
            apply_url=url,
            extra={"id": p["uuid"]},
        )
        pay = p.get("salary") or {}
        interval = INTERVALS.get(((pay.get("type") or {}).get("salaryType") or "").lower())
        if interval and (pay.get("minimum") or pay.get("maximum")):
            stub.salary_min, stub.salary_max = pay.get("minimum"), pay.get("maximum")
            stub.salary_currency, stub.salary_interval = "SGD", interval
        return stub
