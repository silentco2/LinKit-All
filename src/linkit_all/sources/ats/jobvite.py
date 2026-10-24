"""Jobvite careersites (jobs.jobvite.com/<board>): the listing page links every posting, each
posting page carries a schema.org JobPosting. Logic adapted from freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator

from linkit_all.sources.ats._f13 import get_page, name_from_slug
from linkit_all.sources.ats._f16 import chunks, ld_stub, links, page_text
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

_JOB = re.compile(r"/job/([A-Za-z0-9]+)(?:[/?#]|$)")  # /<board>/jobs and /jobAlerts don't match


class Jobvite(Source):
    """The board is the careersite slug: `jobs.jobvite.com/<board>`."""

    name = "jobvite"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.jobvite\.com/(?:careers/)?([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        base = f"https://jobs.jobvite.com/{task.board}/"
        resp = await get_page(http, base + "jobs")  # the whole list is one page
        found = links(resp.text, base, lambda h: bool(_JOB.search(h)))
        urls = list(dict.fromkeys(u.split("?")[0] for u in found))  # ?nl=1 etc. are tracking
        for chunk in chunks(urls, start_page):
            stubs = await asyncio.gather(*(self.posting(http, u, task.board) for u in chunk))
            yield [s for s in stubs if s]

    @staticmethod
    async def posting(http: Http, url: str, board: str) -> JobStub | None:
        m = _JOB.search(url)
        html = await page_text(http, url) if m else None
        found = job_postings(html)[:1] if html else []
        if not m or not found:
            return None
        return ld_stub(
            found[0],
            source="jobvite",
            url=url,
            company=name_from_slug(board),
            extra={"board": board, "id": m[1]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if stub.description:
            return stub
        full = await self.posting(http, stub.url, stub.extra.get("board", ""))
        return stub.model_copy(update={"description": full.description}) if full else stub
