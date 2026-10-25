"""Compleo (jobs.compleo.app, a Brazilian ATS): one platform sitemap, JobPosting JSON-LD per page.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub

SITEMAP = "https://jobs.compleo.app/sitemap.xml"
PAGE = 20  # job pages per checkpoint
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_ID = re.compile(r"/jobdetail/([A-Za-z0-9]+)/?$")


class Compleo(Source):
    """The board is the tenant's path segment: `jobs.compleo.app/<board>/jobdetail/<code>`."""

    name = "compleo"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.compleo\.app/([\w-]+)/", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        # The sitemap covers every tenant; the trailing slash keeps "wafx" out of "wafxpro".
        prefix = f"https://jobs.compleo.app/{task.board}/jobdetail/"
        sitemap = (await get_page(http, SITEMAP)).text
        urls = sorted({u for u in _LOC.findall(sitemap) if u.startswith(prefix) and _ID.search(u)})
        for page in range(start_page, (len(urls) + PAGE - 1) // PAGE):
            stubs = []
            for url in urls[page * PAGE : (page + 1) * PAGE]:
                resp = await http.get(url)
                if resp.status_code in (404, 410):  # closed since the sitemap
                    continue
                resp.raise_for_status()
                postings = job_postings(resp.text)[:1]
                # The employer is the posting's, not the board's: a tenant may recruit for others.
                stubs += [
                    self.stub(p, url, task.board) for p in postings if p.get("hiringOrganization")
                ]
            yield stubs

    def stub(self, posting: dict[str, Any], url: str, board: str) -> JobStub:
        stub = to_stub(posting, self.name, url, self.name)
        return stub.model_copy(
            update={
                "remote": stub.remote or remote_from_text(stub.location, stub.title),
                "extra": {**stub.extra, "board": board, "id": url.rstrip("/").rsplit("/", 1)[-1]},
            }
        )
