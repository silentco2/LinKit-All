"""Deutsche Bahn jobs through db.jobs, the search front over DB's Avature tenant
(jobs.deutschebahngroup.careers; both share job ids). The search page's server-rendered results
endpoint takes any page size, so one 1000-hit page, newest first, covers the board's recent
postings; ties on the publication date reorder between requests, which a large page keeps rare.
The list has no body: the posting page's JobPosting data gives it.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import absolute, get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import node_text
from linkit_all.sources.tasks import careers_task, fresh, limited
from linkit_all.sources.text import html_to_text

ORIGIN = "https://db.jobs"
SEARCH = f"{ORIGIN}/service/search/de-de/5441588"  # DB's search-config id, stable per portal
PER_PAGE = 1000
MAX_PAGES = 5
MAX_JOBS = 1000
_ID = re.compile(r"[?&]jobId=(\d+)")


class DeutscheBahn(Source):
    name = "deutschebahn"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    def page_timeout(self, task: Task) -> float:
        return 1800.0  # one 1000-hit page is a few MB

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, start_page), MAX_JOBS):
            yield page

    async def _pages(self, http: Http, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            query = f"?query=&sort=pubExternalDate_tdt&itemsPerPage={PER_PAGE}&pageNum={page}"
            stubs = fresh(self.hits((await get_page(http, SEARCH + query)).text), seen)
            if not stubs:
                return
            yield stubs

    def hits(self, html: str) -> list[JobStub]:
        stubs = []
        for a in LexborHTMLParser(html).css("a.m-search-hit"):
            url = absolute(a.attributes.get("href"), ORIGIN)
            jid = a.attributes.get("data-job-id") or ((m := _ID.search(url)) and m[1]) or ""
            title = node_text(a.css_first(".m-search-hit__title-text"))
            if not (jid and title and url.startswith(ORIGIN)):
                continue
            place = next(
                (node_text(li) for li in a.css("li") if li.css_first('i[aria-label="Arbeitsort"]')),
                "",
            )
            stubs.append(
                JobStub(
                    source=self.name,
                    url=url,
                    title=title,
                    company="Deutsche Bahn",
                    location=place,
                    ats=self.name,
                    apply_url=url,
                    remote=remote_from_text(place, title),
                    extra={"id": jid},
                )
            )
        return stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        body = html_to_text(str(found[0].get("description") or "")) if found else ""
        return stub.model_copy(update={"description": body}) if body else stub
