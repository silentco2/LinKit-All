"""JobTech / Platsbanken, the Swedish Public Employment Service's open JobStream feed of recent ad
changes. Ads flagged removed are skipped. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

API = "https://jobstream.api.jobtechdev.se/stream"
PAGE = 100
# ponytail: the whole window is read as one JSON body (no incremental parse), so it is capped;
# switch to a streamed decode if a longer window is ever wanted.
MAX_DAYS = 7


class JobTech(Source):
    name = "jobtech"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        since = utcnow() - timedelta(days=min(task.posted_within_days, MAX_DAYS))
        resp = await http.get(
            API,
            params={"date": since.strftime("%Y-%m-%dT%H:%M:%S")},
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        stubs = [s for r in resp.json() if (s := self.stub(r))]
        stubs.sort(key=lambda s: s.posted_at or since, reverse=True)  # the cap keeps the newest
        stubs = stubs[: task.limit]
        for i in range(start_page * PAGE, len(stubs), PAGE):
            yield stubs[i : i + PAGE]

    def stub(self, it: dict[str, Any]) -> JobStub | None:
        emp = it.get("employer") or {}
        # `workplace` is the trading name; `name` is often a numbered shell company.
        company = emp.get("workplace") or emp.get("name")
        if it.get("removed") or not (it.get("id") and it.get("webpage_url") and company):
            return None
        desc = it.get("description") or {}
        addr = it.get("workplace_address") or {}
        return JobStub(
            source=self.name,
            url=it["webpage_url"],
            title=(it.get("headline") or "").strip(),
            company=company,
            location=", ".join(
                p for p in (addr.get("municipality"), addr.get("region"), addr.get("country")) if p
            ),
            description=strip_html(desc.get("text_formatted") or desc.get("text") or ""),
            posted_at=from_iso(it.get("publication_date")),
            apply_url=(it.get("application_details") or {}).get("url") or it["webpage_url"],
            ats=self.name,
            extra={"id": it["id"]},
        )
