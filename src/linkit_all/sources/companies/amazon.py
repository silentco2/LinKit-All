"""Amazon's careers search (www.amazon.jobs): a keyless JSON endpoint, newest first, full HTML
description inline. Single-company plugin. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import paged, strip_html
from linkit_all.sources.companies._f41 import ats_of, limited, query_tasks
from linkit_all.sources.http import Http

BASE = "https://www.amazon.jobs"
PAGE = 100


def _posted(value: str | None) -> datetime | None:
    try:  # "June 15, 2026"
        return datetime.strptime((value or "").strip(), "%B %d, %Y")
    except ValueError:
        return None


class Amazon(Source):
    name = "amazon"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            params = {"result_limit": PAGE, "offset": offset, "sort": "recent"}
            if task.query:
                params["base_query"] = task.query
            data = await http.get_json(f"{BASE}/en/search.json", params=params)
            return data.get("jobs") or [], data.get("hits")

        async def stubs() -> AsyncIterator[list[JobStub]]:
            async for jobs in paged(fetch, PAGE, start_page):
                yield [s for j in jobs if (s := self.stub(j))]

        async for page in limited(stubs(), task.limit):
            yield page

    def stub(self, j: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(j.get("title") or "").split())
        if not title or not j.get("id_icims") or not j.get("job_path"):
            return None
        url = BASE + j["job_path"]
        location = (j.get("normalized_location") or "").strip()
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Amazon",
            location=location,
            description=strip_html(j.get("description") or ""),
            posted_at=_posted(j.get("posted_date")),
            ats=ats_of(url, self.name),
            apply_url=url,
            extra={"id": str(j["id_icims"])},
        )
