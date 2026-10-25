"""JobStash (jobstash.xyz), a Web3 job aggregator; its public list endpoint carries every body.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import mode
from linkit_all.sources.tasks import feed_task

API = "https://middleware.jobstash.xyz/jobs/list"
DETAIL_URL = "https://jobstash.xyz/jobs/{}/details"  # for a gated posting that has no apply link
PAGE = 200
_SECTIONS = (("responsibilities", "Responsibilities"), ("requirements", "Requirements"),
             ("benefits", "Benefits"))  # fmt: skip


class JobStash(Source):
    name = "jobstash"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, ceil(task.limit / PAGE) + 1):
            data = await http.get_json(API, params={"page": page, "limit": PAGE})
            rows = data.get("data") or []
            if not rows:
                return
            if stubs := [s for r in rows if (s := self.stub(r))]:
                yield stubs
            if page * PAGE >= data.get("total", 0):
                return

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        org = (p.get("organization") or {}).get("name")
        if not (p.get("shortUUID") and org and p.get("title")):
            return None
        page = DETAIL_URL.format(p["shortUUID"])
        location = p.get("location") or ""
        return JobStub(
            source=self.name,
            url=page,  # the id stays recoverable from the url
            title=p["title"],
            company=org,
            location=location,
            description=self.body(p),
            posted_at=from_epoch_ms(p.get("timestamp")),
            apply_url=p.get("url") or page,
            remote=mode(p.get("locationType")) or remote_from_text(location),
            ats=self.name,
            extra={"id": p["shortUUID"]},
        )

    @staticmethod
    def body(p: dict[str, Any]) -> str:
        parts = [p.get("description") or ""]
        for key, heading in _SECTIONS:
            if items := p.get(key):
                parts.append(heading + "\n" + "\n".join(f"- {i}" for i in items))
        return "\n\n".join(x.strip() for x in parts if x.strip())
