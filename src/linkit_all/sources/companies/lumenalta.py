"""Lumenalta's own careers API (lumenalta.com/api/jobs): a remote-only consultancy whose paged
list carries every posting with its plain-text description. A single-company plugin, not an ATS.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http

HOST = "lumenalta.com"
LIMIT = 100
API = "https://{host}/api/jobs?page={page}&limit={limit}"


class Lumenalta(Source):
    name = "lumenalta"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "lumenalta:careers", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            url = API.format(host=task.board, page=offset // LIMIT + 1, limit=LIMIT)
            data = await http.get_json(url)
            return data.get("data") or [], (data.get("meta") or {}).get("total")

        async for items in paged(fetch, LIMIT, start_page):
            yield [s for j in items if (s := self.stub(j, task.board))]

    def stub(self, j: dict[str, Any], host: str) -> JobStub | None:
        title = " ".join((j.get("name") or "").split())
        if not j.get("_id") or not j.get("slug") or not title:
            return None
        url = f"https://{host}/careers/{j['slug']}"
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Lumenalta",
            location="Remote",  # remote-only; the API has no location field
            description=(j.get("description") or "").strip(),
            ats=self.name,
            apply_url=url,
            remote="remote",
            extra={"id": j["_id"]},
        )
