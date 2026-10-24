"""WordPress career sites built on WP Job Manager with a Yoast SEO sitemap: the sitemap index points
to a `job_listing` sub-sitemap, and each job page carries a schema.org JobPosting.
Logic adapted from freehire (MIT)."""

import html
import re
from collections.abc import AsyncIterator

from linkit_all.sources.ats._f13 import get_page, name_from_host, sitemap_locs
from linkit_all.sources.ats._f15 import fetch_html, paged_postings, posting_stub
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http

_JOB = re.compile(r"/job/(\d+)-")  # /job/<numeric id>-<slug>/; other sitemap entries are not jobs


class WPYoast(Source):
    """The board is the career site's host: `wpyoast:careers.theplanetgroup.com`. Any WordPress
    site can be one, so there is no URL pattern: name it in the company list."""

    name = "wpyoast"
    kind = "ats"

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board
        index = (await get_page(http, f"https://{host}/sitemap.xml")).text
        # Found through the index, not guessed: the file's name differs across Yoast versions.
        sitemap = next((loc for loc in sitemap_locs(index) if "job_listing" in loc), None)
        if sitemap is None:  # no job_listing sub-sitemap: no postings, not an error
            return
        jobs = {
            m[1]: loc
            for loc in sitemap_locs((await get_page(http, sitemap)).text)
            if (m := _JOB.search(loc))
        }

        async def build(id: str) -> JobStub | None:
            page = await fetch_html(http, jobs[id])
            if page is None:
                return None
            stub = posting_stub(
                page, source=self.name, url=jobs[id], board=host, id=id,
                company=name_from_host(host), escaped=False,
            )  # fmt: skip
            # The title keeps its HTML entities in the JSON ("&#8211;").
            return stub.model_copy(update={"title": html.unescape(stub.title)}) if stub else None

        async for stubs in paged_postings(list(jobs), start_page, build):
            yield stubs
