"""The Muse (themuse.com), a US-heavy aggregator of well-known employers; its public jobs API
returns the full description inline. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

LIST = "https://www.themuse.com/api/public/jobs"
MAX_PAGES = 99  # the API refuses pages past ~99 whatever page_count claims


class TheMuse(Source):
    name = "themuse"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        count = 0
        for page in range(start_page + 1, MAX_PAGES + 1):  # pages are 1-based
            resp = await http.get(LIST, params={"page": page})
            if resp.status_code == 400 and page > start_page + 1:
                return  # "page is too high": the real ceiling, keep what we have
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("results") or []
            if not rows:
                return
            stubs = [s for r in rows if (s := self.stub(r))]
            yield stubs
            count += len(stubs)
            if count >= task.limit or page >= (data.get("page_count") or 0):
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        company = (r.get("company") or {}).get("name")
        url = (r.get("refs") or {}).get("landing_page")
        if not (r.get("id") and r.get("name") and company and url):
            return None
        location = next((loc["name"] for loc in r.get("locations") or [] if loc.get("name")), "")
        return JobStub(
            source=self.name,
            url=url,
            title=r["name"].strip(),
            company=company,
            location=location,
            description=strip_html(r.get("contents") or ""),
            posted_at=from_iso(r.get("publication_date")),
            apply_url=url,
            remote=remote_from_text(location),
            extra={"id": r["id"]},
        )
