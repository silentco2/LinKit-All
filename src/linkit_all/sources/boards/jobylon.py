"""Jobylon (emp.jobylon.com), the Nordic ATS vendor's job portal: the job sitemap lists every
posting and each page carries a schema.org JobPosting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.ats._f16 import CHUNK, page_text
from linkit_all.sources.ats._f17 import hydrate
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.boards._f31 import board_stub, sitemap_urls
from linkit_all.sources.http import Http

INDEX = "https://emp.jobylon.com/sitemap.xml"
_JOB = re.compile(r"^https://emp\.jobylon\.com/jobs/(\d+)")  # company pages are not postings


class Jobylon(Source):
    name = "jobylon"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        # ponytail: sitemap order (all entries are dated alike), capped at task.limit
        urls = await sitemap_urls(http, INDEX, "sitemap-jobs", lambda u: bool(_JOB.search(u)))

        async def build(url: str) -> JobStub | None:
            page, m = await page_text(http, url), _JOB.search(url)
            return board_stub(page, source=self.name, url=url, id=m[1]) if page and m else None

        async for stubs in hydrate(urls[: task.limit], start_page, build, CHUNK):
            yield stubs
