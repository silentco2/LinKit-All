"""JustJoin.it (justjoin.it), a Polish IT job board, through the candidate offers API its own
pages call: newest first, 100 a page, with a cursor for the next. The list has no body.
Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, mode, safe_date
from linkit_all.sources.tasks import all_older, feed_task, limited

API = "https://justjoin.it/api/candidate-api/offers"
JOB = "https://justjoin.it/job-offer/{}"
PAGE = 100
MAX_PAGES = 50


class JustJoin(Source):
    name = "justjoin"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        # ponytail: the cursor is an offset in practice; a resumed run starts at start_page*PAGE.
        async for page in limited(self._pages(http, task, start_page * PAGE), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, offset: int) -> AsyncIterator[list[JobStub]]:
        for _ in range(MAX_PAGES):
            params = {
                "from": offset,
                "itemsCount": PAGE,
                "currency": "pln",
                "orderBy": "descending",
                "sortBy": "publishedAt",
                "keywordType": "any",
                "isPromoted": "true",
            }
            data = await http.get_json(API, params=params)
            rows = data.get("data") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("justjoin: the response carries no data array")
            stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
            yield stubs
            cursor = ((data.get("meta") or {}).get("next") or {}).get("cursor")
            if cursor is None or not rows or all_older(stubs, task):
                return
            offset = int(cursor)

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        slug, title, company = (
            str(r.get("slug") or "").strip(),
            clean(r.get("title")),
            clean(r.get("companyName")),
        )
        if not (slug and title and company):
            return None
        cities = [clean(p.get("city")) for p in r.get("locations") or [] if isinstance(p, dict)]
        where = ", ".join(dict.fromkeys(c for c in (*cities, clean(r.get("city"))) if c))
        return JobStub(
            source=self.name,
            url=JOB.format(slug),
            title=title,
            company=company,
            location=where,
            posted_at=safe_date(r.get("lastPublishedAt")) or safe_date(r.get("publishedAt")),
            ats=self.name,
            apply_url=JOB.format(slug),
            remote=mode(str(r.get("workplaceType") or "")),
            extra={"id": slug},
        )
