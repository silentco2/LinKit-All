"""iCIMS career sites (careers-{board}.icims.com, or a vanity host): the sitemap lists the postings
and each posting's ?in_iframe=1 fragment carries a schema.org JobPosting. Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import fetch_html, get_page, paged_postings, sitemap_locs
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_host, name_from_slug, posting_stub

# /jobs/<id>/<slug>/job (classic) or /jobs/<id>?lang=.. (careers-home); /jobs/search has no id
_JOB = re.compile(r"/jobs/(\d+)(?:[/?#]|$)")


def host_of(board: str) -> str:
    """A bare slug is the classic careers-<slug>.icims.com; a board with a dot is a vanity host."""
    return board if "." in board else f"careers-{board}.icims.com"


class Icims(Source):
    """The board is the iCIMS slug (`360care`), or the full host of a vanity careers site
    (`careers.docusign.com`, the newer careers-home product)."""

    name = "icims"
    kind = "ats"
    url_patterns = (re.compile(r"careers-([\w-]+)\.icims\.com", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board, host = task.board, host_of(task.board)
        vanity = "." in board
        root = (await get_page(http, f"https://{host}/sitemap.xml")).text
        locs = sitemap_locs(root)
        if "<sitemapindex" in root:  # vanity sites nest their <url> entries one level down
            locs = [u for sub in locs for u in sitemap_locs((await get_page(http, sub)).text)]
        jobs: dict[str, str] = {}  # one entry per id: the sitemap repeats a job per language
        for loc in locs:
            if m := _JOB.search(loc):
                jobs.setdefault(m[1], loc)
        company = name_from_host(host) if vanity else name_from_slug(board)

        async def build(job_id: str) -> JobStub | None:
            loc = jobs[job_id]
            frag = (
                f"https://{host}/careers-home/jobs/{job_id}?in_iframe=1"
                if vanity
                else loc + ("&" if "?" in loc else "?") + "in_iframe=1"
            )
            html = await fetch_html(http, frag)
            if html is None:
                return None
            return posting_stub(
                html, source=self.name, url=loc, board=board, id=job_id, company=company
            )

        async for stubs in paged_postings(list(jobs), start_page, build):
            yield stubs
