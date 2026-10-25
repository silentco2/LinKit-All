"""Jobicy (jobicy.com), a remote-jobs aggregator whose public feed carries every body.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

API = "https://jobicy.com/api/v2/remote-jobs"
MAX_COUNT = 50  # the feed's cap: it is the recent window, not a catalogue


class Jobicy(Source):
    name = "jobicy"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        data = await http.get_json(API, params={"count": min(MAX_COUNT, task.limit)})
        if stubs := [s for r in data.get("jobs") or [] if (s := self.stub(r))]:
            yield stubs

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        if not (p.get("id") and p.get("companyName") and p.get("url")):
            return None
        return JobStub(
            source=self.name,
            url=p["url"],
            title=p.get("jobTitle") or "",
            company=p["companyName"],
            location=p.get("jobGeo") or "",
            description=strip_html(p.get("jobDescription") or ""),
            posted_at=from_iso(p.get("pubDate")),
            apply_url=p["url"],
            remote="remote",  # the site lists remote jobs only
            ats=self.name,
            extra={"id": p["id"]},
        )
