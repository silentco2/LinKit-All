"""Luxoft's own careers site (career.luxoft.com): a paged /jobs listing links each posting, whose
page carries a schema.org JobPosting. A single-company plugin, not an ATS. Logic adapted from
freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f13 import get_page
from linkit_all.sources.ats._f16 import ld_stub, links, page_text
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

HOST = "career.luxoft.com"
PER_PAGE = 60  # the largest page size the listing offers: about 24 pages for ~1,400 jobs
MAX_PAGES = 100  # a listing that clamps ?page=N to its last page must not loop
_JOB = re.compile(r"/jobs/[^/?#]*-(\d+)(?:[/?#]|$)")  # the bare /jobs and ?page=N don't match


class Luxoft(Source):
    name = "luxoft"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "luxoft:jobs", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            # /jobs?page=1 redirects to a broken address, so the first page has no page parameter.
            url = f"https://{task.board}/jobs?perPage={PER_PAGE}" + (
                f"&page={page}" if page > 1 else ""
            )
            resp = await get_page(http, url)
            fresh = [
                u for u in links(resp.text, url, lambda h: bool(_JOB.search(h))) if u not in seen
            ]
            if not fresh:  # an empty page, or one clamped to the last page: the end
                return
            seen.update(fresh)
            stubs = await asyncio.gather(*(self.posting(http, u) for u in fresh))
            yield [s for s in stubs if s]

    @staticmethod
    async def posting(http: Http, url: str) -> JobStub | None:
        m = _JOB.search(url)
        html = await page_text(http, url) if m else None
        found = job_postings(html)[:1] if html else []
        if not m or not found:
            return None
        stub = ld_stub(
            found[0], source="luxoft", url=url, company="Luxoft", escaped=True, extra={"id": m[1]}
        )
        # the company's own site: there is no ATS to apply on
        return stub.model_copy(update={"ats": None}) if stub else None

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if stub.description:
            return stub
        full = await self.posting(http, stub.url)
        return stub.model_copy(update={"description": full.description}) if full else stub
