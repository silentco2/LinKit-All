"""The Hub (thehub.io), the Nordic startup job board: the sitemap index names a jobs sitemap and
each posting page carries a JobPosting block with an HTML-escaped description.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.ats._f13 import sitemap_locs
from linkit_all.sources.ats._f16 import ld_stub, page_text
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.boards._f32 import posting_pages, sitemap_text, sitemap_urls
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

INDEX = "https://thehub.io/sitemap.xml"
_ID = re.compile(r"/jobs/([0-9a-f]{12,})", re.I)


class TheHub(Source):
    name = "thehub"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        index = await sitemap_text(http, INDEX)
        sub = next((u for u in sitemap_locs(index) if "jobs" in u), None)
        if sub is None:
            return
        urls = sitemap_urls(await sitemap_text(http, sub), lambda u: bool(_ID.search(u)))

        async def build(url: str) -> JobStub | None:
            text = await page_text(http, url)
            postings = job_postings(text) if text else []
            if not postings or not (m := _ID.search(url)):
                return None
            stub = ld_stub(
                postings[0], source=self.name, url=url, company="", extra={"id": m[1]}, escaped=True
            )
            return stub if stub and stub.company else None

        async for page in posting_pages(urls, start_page, task.limit, build):
            yield page
