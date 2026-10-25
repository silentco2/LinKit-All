"""Remote OK (remoteok.com), a remote-jobs aggregator. One /api feed of roughly the latest hundred
postings, body inline. Remote OK's API terms ask for a link back and a mention as the source:
every job URL here points at remoteok.com, and the UI shows the source name next to each job.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

API = "https://remoteok.com/api"


class RemoteOK(Source):
    name = "remoteok"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        feed = await http.get_json(API)
        if start_page == 0:  # the feed's first element is a legal notice, dropped by `stub`
            stubs = [s for r in feed if (s := self.stub(r))][: task.limit]
            if stubs:
                yield stubs

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        company = (p.get("company") or "").strip()
        if not p.get("id") or not company or not p.get("url"):
            return None
        stub = JobStub(
            source=self.name,
            url=p["url"],
            title=(p.get("position") or "").strip(),
            company=company,
            location=(p.get("location") or "").strip(),
            description=strip_html(p.get("description") or ""),
            posted_at=from_iso(p.get("date")),
            ats=self.name,
            apply_url=p["url"],
            remote="remote",  # the board lists remote jobs only
            extra={"id": str(p["id"])},
        )
        if p.get("salary_min") or p.get("salary_max"):
            stub.salary_min, stub.salary_max = (
                p.get("salary_min") or None,
                p.get("salary_max") or None,
            )
            stub.salary_currency, stub.salary_interval = "USD", "year"
        return stub
