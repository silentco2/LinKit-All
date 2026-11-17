"""4 Day Week (4dayweek.io), a board of four-day-week and reduced-hours roles. Its public JSON
API pages 25 postings at a time, newest first, with no posting address: the posting page is
built from the slug. Expired postings are dropped. Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean
from linkit_all.sources.tasks import all_older, feed_task, limited

API = "https://4dayweek.io/api/jobs"
JOB = "https://4dayweek.io/job/{}"
PAGE = 25
MAX_PAGES = 50
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*$")


class FourDayWeek(Source):
    name = "4dayweek"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(API, params={"page": page})
            rows = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("4dayweek: the response carries no jobs array")
            stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
            yield stubs
            if data.get("has_more") is False or len(rows) < PAGE or all_older(stubs, task):
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        company = clean(r.get("company_name")) or clean((r.get("company") or {}).get("name"))
        title, slug = clean(r.get("title")), str(r.get("slug") or "").strip()
        if r.get("is_expired") is True or not (title and company and _SLUG.match(slug)):
            return None
        places = [p for p in r.get("locations") or [] if isinstance(p, dict)]
        first = places[0] if places else {}
        where = ", ".join(x for x in (clean(first.get("city")), clean(first.get("country"))) if x)
        remote = "remote" in (r.get("work_arrangement"), first.get("work_arrangement"))
        posted = r.get("posted")
        return JobStub(
            source=self.name,
            url=JOB.format(slug),
            title=title,
            company=company,
            location=where or ("Remote" if remote else ""),
            posted_at=from_epoch_ms(posted * 1000) if isinstance(posted, int | float) else None,
            ats=self.name,
            apply_url=JOB.format(slug),
            remote="remote" if remote else None,
            extra={"id": str(r.get("id") or slug)},
        )
