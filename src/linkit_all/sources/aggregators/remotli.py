"""Remotli (remotli.ch), a Swiss remote-jobs aggregator. The /api/jobs endpoint pages by number
and carries every body inline. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from math import ceil
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.tasks import all_older, feed_task

API = "https://remotli.ch/api/jobs"
PAGE = 20


class Remotli(Source):
    name = "remotli"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, ceil(task.limit / PAGE) + 1):
            try:
                data = await http.get_json(API, params={"page": page})
            except (httpx.HTTPError, RetryableStatus):
                if page == start_page + 1:
                    raise
                return  # a later page failing ends the walk with what was gathered
            # each row is wrapped one level deep under its own "jobs" key
            stubs = [s for w in data.get("jobs") or [] if (s := self.stub(w.get("jobs") or {}))]
            if stubs:
                yield stubs
            if page >= (data.get("pagination") or {}).get("totalPages", 0) or all_older(
                stubs, task
            ):
                return

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        company, url = (p.get("company") or "").strip(), p.get("applyUrl")
        if not (p.get("id") and company and url) or p.get("status") != "active":
            return None
        location = (p.get("location") or "").strip()
        return JobStub(
            source=self.name,
            url=url,
            title=(p.get("title") or "").strip(),
            company=company,
            location=location,
            description=strip_html(p.get("description") or ""),
            posted_at=from_iso(p.get("publishedAt")),
            ats=self.name,
            apply_url=url,
            # mixes onsite Swiss postings with remote ones and has no structured remote flag
            remote=remote_from_text(location),
            extra={"id": str(p["id"])},
        )
