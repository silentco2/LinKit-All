"""OCC Mundial (www.occ.com.mx), Mexico's main general job board. No public API: search pages
are server-rendered cards. Paging is a path suffix ("de-python-pagina-2"); query parameters
silently serve page 1 again, so the walk also stops when a page brings nothing new. Cards have
no date or body: `fetch_details` reads the posting page's JobPosting data.
Logic adapted from career-ops (MIT)."""

import re
import unicodedata
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import node_text
from linkit_all.sources.tasks import fresh, limited, query_tasks
from linkit_all.sources.text import html_to_text

ORIGIN = "https://www.occ.com.mx"
JOB = "https://www.occ.com.mx/empleo/oferta/{}/"
MAX_PAGES = 10


def slugify(text: str) -> str:
    plain = unicodedata.normalize("NFD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def search_url(query: str, page: int) -> str:
    q = slugify(query)
    return f"{ORIGIN}/empleos/de-{q}{f'-pagina-{page}' if page > 1 else ''}/"


class Occ(Source):
    name = "occ"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            stubs = fresh(
                self.cards((await get_page(http, search_url(task.query, page))).text), seen
            )
            if not stubs:
                return
            yield stubs

    def cards(self, html: str) -> list[JobStub]:
        stubs = []
        for card in LexborHTMLParser(html).css("div.card-job-offer"):
            jid = (card.attributes.get("data-id") or "").strip()
            title = node_text(card.css_first("h2"))
            if not (jid.isdigit() and title):
                continue
            company = node_text(card.css_first(".h-\\[21px\\] span"))
            where = node_text(card.css_first(".no-alter-loc-text p"))
            stubs.append(
                JobStub(
                    source=self.name,
                    url=JOB.format(jid),
                    title=title,
                    company=company or "Empresa confidencial",
                    location=where,
                    ats=self.name,
                    apply_url=JOB.format(jid),
                    remote=remote_from_text(where, title),
                    extra={"id": jid},
                )
            )
        return stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        body = html_to_text(str(found[0].get("description") or "")) if found else ""
        return stub.model_copy(update={"description": body}) if body else stub
