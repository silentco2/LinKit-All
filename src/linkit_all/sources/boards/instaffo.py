"""Instaffo (jobs.instaffo.com), a German tech-hiring board: the job sitemap lists the postings and
each page carries a schema.org JobPosting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import timedelta

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import CHUNK, child_sitemap_urls, hydrate, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import board_stub
from linkit_all.sources.tasks import feed_task

INDEX = "https://jobs.instaffo.com/sitemap.xml"
# every posting is listed per locale under one id; only the canonical /de/ twin is read
_JOB = re.compile(r"/de/job/([^/?#]+-[0-9a-f]{12})$")
MAX_AGE = timedelta(days=365)  # the board keeps old postings online; an undated one is dropped


class Instaffo(Source):
    name = "instaffo"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        # ponytail: sitemap order, capped at task.limit; no per-posting date to sort on
        urls = await child_sitemap_urls(http, INDEX, "sitemap-jobs", lambda u: bool(_JOB.search(u)))

        async def build(url: str) -> JobStub | None:
            page, m = await page_text(http, url), _JOB.search(url)
            stub = board_stub(page, source=self.name, url=url, id=m[1]) if page and m else None
            if stub is None or stub.posted_at is None or utcnow() - stub.posted_at > MAX_AGE:
                return None
            return stub

        async for stubs in hydrate(urls[: task.limit], start_page, build, CHUNK):
            yield stubs
