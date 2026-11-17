"""Bulldogjob (bulldogjob.pl), a Polish tech job board. No public API: the listing pages carry
their postings in `__NEXT_DATA__` (50 a page, with the total). The search root without a page
answers 404, so every request names its page. Cards have no date or body: `fetch_details` reads
the posting page's JobPosting data. Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import clean, next_data, safe_date
from linkit_all.sources.tasks import feed_task, limited
from linkit_all.sources.text import html_to_text

LIST = "https://bulldogjob.pl/companies/jobs/s/page,{}"
JOB = "https://bulldogjob.pl/companies/jobs/{}"
PAGE = 50
MAX_PAGES = 100


class Bulldogjob(Source):
    name = "bulldogjob"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = next_data((await get_page(http, LIST.format(page))).text) or {}
            props = (data.get("props") or {}).get("pageProps") or {}
            rows = props.get("jobs") if isinstance(props, dict) else None
            if not isinstance(rows, list):
                raise ValueError("bulldogjob: the page carries no pageProps.jobs (markup changed?)")
            yield [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
            total = props.get("totalCount")
            if len(rows) < PAGE or (isinstance(total, int) and page * PAGE >= total):
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        jid, title = str(r.get("id") or "").strip(), clean(r.get("position"))
        company = clean((r.get("company") or {}).get("name"))
        if not (jid and title and company):
            return None
        own = JOB.format(quote(jid, safe=""))
        external = str(r.get("redirectTo") or "").strip()
        where = ", ".join(
            x for x in ("Remote" if r.get("remote") is True else "", clean(r.get("city"))) if x
        )
        return JobStub(
            source=self.name,
            url=own,
            title=title,
            company=company,
            location=where,
            ats=self.name,
            apply_url=external if external.startswith("https://") else own,
            remote="remote" if r.get("remote") is True else None,
            extra={"id": jid, "language": r.get("locale")},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        if not found:
            return stub
        update = {
            "description": html_to_text(str(found[0].get("description") or "")),
            "posted_at": safe_date(found[0].get("datePosted")),
        }
        return stub.model_copy(update={k: v for k, v in update.items() if v})
