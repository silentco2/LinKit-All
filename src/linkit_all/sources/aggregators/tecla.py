"""Tecla (app.tecla.io), a remote-only marketplace of LatAm engineering vacancies; the public
list is paged and carries each posting's employer and a truncated description.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

LIST = "https://api.tecla.io/api/jobs/getPublicJobs/"
JOB_URL = "https://app.tecla.io/job?id={}"
MAX_PAGES = 100  # a runaway guard


class Tecla(Source):
    name = "tecla"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        count = 0
        for page in range(start_page + 1, MAX_PAGES + 1):  # pages are 1-based
            data = (await http.get_json(LIST, params={"page": page})).get("data") or {}
            rows = data.get("jobs") or []
            if not rows:
                return
            stubs = [s for r in rows if (s := self.stub(r))]
            yield stubs
            count += len(stubs)
            if count >= task.limit or page >= (data.get("pagination") or {}).get("countPages", 0):
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        company = (r.get("company") or {}).get("name")
        if not (r.get("id") and r.get("name") and company):
            return None
        url = JOB_URL.format(r["id"])
        return JobStub(
            source=self.name,
            url=url,
            title=r["name"].strip(),
            company=company,
            description=strip_html(r.get("description") or ""),  # truncated by Tecla
            posted_at=from_iso(r.get("createdAt") or None),  # zone-less
            apply_url=url,
            remote="remote",  # the marketplace is remote-only
            extra={"id": r["id"]},
        )
