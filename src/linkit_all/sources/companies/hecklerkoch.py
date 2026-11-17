"""Heckler & Koch's vacancy list (www.heckler-koch.com/de/Karriere/Stellenangebote): a Nuxt page
whose cards are server-rendered, so one request lists every posting. Each card links its apply
page on karriere.heckler-koch.com/jobposting/{hash}; the hash is the id. No place or date on
the cards (the company is almost single-site), so none is guessed.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import node_text
from linkit_all.sources.tasks import careers_task
from linkit_all.sources.text import html_to_text

LIST = "https://www.heckler-koch.com/de/Karriere/Stellenangebote"
_POSTING = re.compile(r"^https://karriere\.heckler-koch\.com/jobposting/([a-z0-9]+)", re.I)


class HecklerKoch(Source):
    name = "hecklerkoch"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one page holds the whole board
            return
        stubs = self.cards((await get_page(http, LIST)).text)
        if stubs:
            yield stubs

    def cards(self, html: str) -> list[JobStub]:
        found: dict[str, JobStub] = {}
        for a in LexborHTMLParser(html).css("a[href]"):
            m = _POSTING.match(a.attributes.get("href") or "")
            title = node_text(a.css_first("h3"))
            if not (m and title) or m[1] in found:
                continue
            field = node_text(a.css_first("p"))
            found[m[1]] = JobStub(
                source=self.name,
                url=m[0],
                title=title,
                company="Heckler & Koch",
                ats=self.name,
                apply_url=m[0],
                extra={"id": m[1], "field": field},
            )
        return list(found.values())

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        body = html_to_text(str(found[0].get("description") or "")) if found else ""
        return stub.model_copy(update={"description": body}) if body else stub
