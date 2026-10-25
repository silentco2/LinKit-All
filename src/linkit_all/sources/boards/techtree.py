"""TechTree (jobs.techtree.dev), a Latin-American tech job board: the sitemap lists every posting,
each page carries a JobPosting block and the description in its `.prose` element.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.ats._f16 import ld_stub, page_text
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.boards._f32 import posting_pages, sitemap_text, sitemap_urls
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

SITEMAP = "https://jobs.techtree.dev/sitemap.xml"
_ID = re.compile(r"/job/([0-9a-f-]{36})", re.I)


class TechTree(Source):
    name = "techtree"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        urls = sitemap_urls(await sitemap_text(http, SITEMAP), lambda u: bool(_ID.search(u)))

        async def build(url: str) -> JobStub | None:
            text = await page_text(http, url)
            postings = job_postings(text) if text else []
            body = LexborHTMLParser(text).css_first(".prose") if postings and text else None
            if body is None or not (m := _ID.search(url)):  # no posting or body: not stored empty
                return None
            stub = ld_stub(postings[0], source=self.name, url=url, company="", extra={"id": m[1]})
            if stub is None or not stub.company:
                return None
            return stub.model_copy(update={"description": strip_html(body.html or "")})

        async for page in posting_pages(urls, start_page, task.limit, build):
            yield page
