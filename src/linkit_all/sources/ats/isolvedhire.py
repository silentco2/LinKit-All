"""iSolved Hire ({board}.isolvedhire.com) and ApplicantPro ({board}.applicantpro.com): one Vue
platform on two domains. The sitemap lists the postings and each posting page carries a schema.org
JobPosting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.sources.ats._f13 import get_page, name_from_slug, sitemap_locs
from linkit_all.sources.ats._f15 import fetch_html, paged_postings, posting_stub
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http

_JOB = re.compile(r"/jobs/(\d+)")  # the sitemap lists /jobs/<id> and /jobs/<id>.html
# What the platform answers (HTTP 200, HTML) for a board it does not serve; matched on a stable
# fragment of the sentence, case-insensitively, within the head of the response.
_GONE = ("typed the url for this website incorrectly", "career site has been disabled")


class _Family(Source):
    host: str

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.lower()
        site = f"{board}.{self.host}"
        sitemap = (await get_page(http, f"https://{site}/sitemap.xml")).text
        if any(notice in sitemap[:512].lower() for notice in _GONE):
            raise Unsupported(f"{self.name} board {board} is not served ({site} has no site)")
        ids = list(dict.fromkeys(m[1] for loc in sitemap_locs(sitemap) if (m := _JOB.search(loc))))

        async def build(job_id: str) -> JobStub | None:
            url = f"https://{site}/jobs/{job_id}"
            html = await fetch_html(http, url)
            if html is None:
                return None
            return posting_stub(
                html, source=self.name, url=url, board=board, id=job_id,
                company=name_from_slug(board),
            )  # fmt: skip

        async for stubs in paged_postings(ids, start_page, build):
            yield stubs


class IsolvedHire(_Family):
    name = "isolvedhire"
    kind = "ats"
    host = "isolvedhire.com"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([\w-]+)\.isolvedhire\.com", re.I),)


class ApplicantPro(_Family):
    name = "applicantpro"
    kind = "ats"
    host = "applicantpro.com"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([\w-]+)\.applicantpro\.com", re.I),)
