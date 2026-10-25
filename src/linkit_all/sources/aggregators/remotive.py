"""Remotive (remotive.com), a remote-jobs aggregator. The API asks for only a few requests a day and
serves data 24 hours late, so the whole feed is read once per run, body inline. Its terms ask
for attribution: every job URL points at remotive.com.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

API = "https://remotive.com/api/remote-jobs"


class Remotive(Source):
    name = "remotive"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        data = await http.get_json(API)
        if start_page == 0:
            stubs = [s for r in data.get("jobs") or [] if (s := self.stub(r))][: task.limit]
            if stubs:
                yield stubs

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        company = (p.get("company_name") or "").strip()
        if not p.get("id") or not company or not p.get("url"):
            return None
        return JobStub(
            source=self.name,
            url=p["url"],
            title=(p.get("title") or "").strip(),
            company=company,
            location=(p.get("candidate_required_location") or "").strip(),
            description=strip_html(p.get("description") or ""),
            posted_at=from_iso(p.get("publication_date")),  # zone-less ISO: read as UTC
            ats=self.name,
            apply_url=p["url"],
            remote="remote",  # the board lists remote jobs only
            extra={"id": str(p["id"])},
        )
