"""Flowxtra (app.flowxtra.com), an ATS whose one public API lists the live postings of every
company it hosts, so it is read as a feed, not per company. The listing has no body; rows whose
apply link is not on flowxtra.com are dropped. Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, last_segment, safe_date
from linkit_all.sources.tasks import feed_task, limited

API = "https://app.flowxtra.com/api/central/jobs"
PAGE = 100
MAX_PAGES = 50


class Flowxtra(Source):
    name = "flowxtra"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(
                API, params={"status": "Live", "per_page": PAGE, "page": page}
            )
            inner = data.get("data") if isinstance(data, dict) else None
            rows = inner.get("data") if isinstance(inner, dict) else None
            if not isinstance(inner, dict) or not isinstance(rows, list):
                raise ValueError("flowxtra: the response carries no data.data array")
            yield [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
            if not inner.get("next_page_url") or len(rows) < PAGE:
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        title, company = clean(r.get("title")), clean(r.get("name_company"))
        url = str(r.get("urlJobApplay") or "").strip()  # sic: the API's own spelling
        parts = urlsplit(url)
        if not (title and company) or parts.scheme != "https" or parts.hostname != "flowxtra.com":
            return None
        places = (r.get("city_company"), r.get("state_company"), r.get("country_company"))
        remote = r.get("workplace") == "Remote"
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=", ".join(clean(p) for p in places if clean(p)),
            posted_at=safe_date(r.get("date_share")),
            ats=self.name,
            apply_url=url,
            remote="remote" if remote else None,
            extra={"id": str(r.get("has_id") or last_segment(url))},
        )
