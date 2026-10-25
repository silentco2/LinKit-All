"""Dev Global Jobs (devglobaljobs.com), a global jobs aggregator with a public REST API.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import all_older, feed_task

API = "https://devglobaljobs.com/api/v1/jobs"
PAGE_URL = "https://devglobaljobs.com/jobs/detail/{}"
PAGE = 100
MAX_OFFSET = 10_000  # the API clamps offset paging here


class DevGlobalJobs(Source):
    name = "devglobaljobs"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page, min(ceil(task.limit / PAGE), MAX_OFFSET // PAGE)):
            data = await http.get_json(API, params={"limit": PAGE, "offset": page * PAGE})
            rows = data.get("jobs") or []
            stubs = [s for r in rows if (s := self.stub(r))]
            if stubs:
                yield stubs
            more = (data.get("meta") or {}).get("hasMore")
            if len(rows) < PAGE or not more or all_older(stubs, task):
                return

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        if not (p.get("id") and p.get("title") and p.get("organization")):
            return None
        url = PAGE_URL.format(p["id"])  # the id stays recoverable from the url for fetch_details
        location = (p.get("location") or "").strip()
        return JobStub(
            source=self.name,
            url=url,
            title=p["title"],
            company=p["organization"],
            location=location,
            posted_at=from_iso(p.get("postedAt")),
            apply_url=p.get("url") or url,
            remote=remote_from_text(location),
            extra={"id": p["id"], "category": p.get("category")},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        job_id = stub.url.rstrip("/").rsplit("/", 1)[-1]
        data = await http.get_json(f"{API}/{job_id}")
        text = strip_html(data.get("description") or "", True)
        return stub.model_copy(update={"description": text})
