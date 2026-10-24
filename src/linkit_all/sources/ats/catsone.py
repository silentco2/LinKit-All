"""CATS (catsone.com) career portals: one server-rendered table lists every job.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f12 import get_page, name_from_host
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import absolute
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

_JOB = re.compile(r"/careers/(\d+)/jobs/(\d+)")


class Catsone(Source):
    """The board is the careers host: `acme.catsone.com`, or a custom domain mapped to CATS
    (`catsone:jobs.acme.com`)."""

    name = "catsone"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+\.catsone\.com)/careers", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the portal has no paging
            return
        resp = await get_page(http, f"https://{task.board}/careers")  # redirects to the portal
        company = name_from_host(task.board)
        stubs = []
        for row in LexborHTMLParser(resp.text).css("a.table-row"):
            href = row.attributes.get("href") or ""
            m = _JOB.search(href)
            if not m:
                continue
            title = row.css_first(".title-cell")
            place = row.css_first('[data-label="Location"]')
            location = " ".join(place.text().split()) if place else ""
            url = absolute(href, str(resp.url))
            stubs.append(
                JobStub(
                    source=self.name,
                    url=url,
                    title=" ".join(title.text().split()) if title else "",
                    company=company,
                    location=location,
                    ats=self.name,
                    apply_url=url,
                    remote=remote_from_text(location),
                    extra={"board": task.board, "portal": m[1], "id": m[2]},
                )
            )
        yield list({s.url: s for s in stubs if s.title}.values())

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        body = LexborHTMLParser((await get_page(http, stub.url)).text).css_first(".job-description")
        if body is None:
            return stub
        return stub.model_copy(update={"description": html_to_text(body.html or "")})
