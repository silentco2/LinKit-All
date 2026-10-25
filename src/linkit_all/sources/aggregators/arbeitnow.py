"""Arbeitnow (arbeitnow.com), a mostly German job board whose public feed carries every body.
Logic adapted from freehire (MIT)."""

import html
from collections.abc import AsyncIterator
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import all_older, feed_task

API = "https://www.arbeitnow.com/api/job-board-api"
PAGE = 100  # the feed's page size


class Arbeitnow(Source):
    name = "arbeitnow"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, ceil(task.limit / PAGE) + 1):
            data = await http.get_json(API, params={"page": page})
            rows = data.get("data") or []
            if not rows:
                return
            stubs = [s for r in rows if (s := self.stub(r))]
            yield stubs
            if not (data.get("links") or {}).get("next") or all_older(stubs, task):
                return

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        if not p.get("slug") or not p.get("company_name") or not p.get("url"):
            return None
        body = p.get("description") or ""
        if "&lt;" in body:  # about a tenth of the feed arrives entity-encoded
            body = html.unescape(body)
        location = p.get("location") or ""
        return JobStub(
            source=self.name,
            url=p["url"],
            title=p.get("title") or "",
            company=p["company_name"],
            location=location,
            description=strip_html(body),
            posted_at=from_epoch_ms((p.get("created_at") or 0) * 1000),
            apply_url=p["url"],
            remote="remote" if p.get("remote") else remote_from_text(location),
            extra={"id": p["slug"]},
        )
