"""iTechArt's own careers site (itechartgroup.by): the sitemap lists the /job-openings/<slug>
vacancies and each page carries a schema.org JobPosting. A single-company plugin, not an ATS.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f13 import get_page, sitemap_locs
from linkit_all.sources.ats._f15 import fetch_html, paged_postings, posting_stub
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http

HOST = "itechartgroup.by"
# The slug is the id; the bare /job-openings listing has none and is not a vacancy.
_JOB = re.compile(r"/job-openings/([a-z0-9-]+)(?:[/?#]|$)")


class ITechArt(Source):
    name = "itechart"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "itechart:careers", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        sitemap = (await get_page(http, f"https://{task.board}/sitemap.xml")).text
        jobs = {m[1]: loc for loc in sitemap_locs(sitemap) if (m := _JOB.search(loc))}

        async def build(slug: str) -> JobStub | None:
            html = await fetch_html(http, jobs[slug])
            if html is None:
                return None
            return posting_stub(
                html, source=self.name, url=jobs[slug], board=task.board, id=slug,
                company="iTechArt",
            )  # fmt: skip

        async for stubs in paged_postings(list(jobs), start_page, build):
            yield stubs
