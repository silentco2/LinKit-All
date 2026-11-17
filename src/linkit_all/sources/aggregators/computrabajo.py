"""Computrabajo, a Latin American job board with one host per country (co.computrabajo.com,
mx.computrabajo.com...). No public API: search pages are server-rendered cards. Crawling is
kept deliberately light (3 pages a search). A bot-check page is reported as an error and never
answered. Cards have no date or body: `fetch_details` reads the posting page's JobPosting data.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import absolute, get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import node_text
from linkit_all.sources.tasks import fresh, limited, query_tasks
from linkit_all.sources.text import html_to_text

MAX_PAGES = 3  # also the hard cap: one search never turns into a long crawl
DEFAULT_COUNTRY = "co"
_CHALLENGE = re.compile(
    r"<title[^>]*>[^<]*(?:just a moment|attention required|access denied|acceso denegado)"
    r"|cf-(?:challenge|browser-verification|error-details)|cf-mitigated",
    re.I,
)
_POSTING = re.compile(r"^https://[a-z]{2}\.computrabajo\.com/ofertas-de-trabajo/[^?#]+")


def slug(text: str) -> str:
    return re.sub(r"[^\w]+", "-", text.strip().lower()).strip("-")


class Computrabajo(Source):
    name = "computrabajo"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        country = (task.country or DEFAULT_COUNTRY).lower()[:2]
        base = f"https://{country}.computrabajo.com/trabajo-de-{slug(task.query)}"
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            html = (await get_page(http, base + (f"?p={page}" if page > 1 else ""))).text
            if _CHALLENGE.search(html):
                raise ValueError("computrabajo: the site answered with a bot check (not solved)")
            stubs = fresh(self.cards(html, base), seen)
            if not stubs:  # past the end, or a page parameter the site ignores
                return
            yield stubs

    def cards(self, html: str, base: str) -> list[JobStub]:
        stubs = []
        for card in LexborHTMLParser(html).css("article.box_offer"):
            link = card.css_first("h2 a[href]") or card.css_first("a.js-o-link")
            m = _POSTING.match(absolute(link.attributes.get("href") if link else "", base))
            title = node_text(link)
            jid = card.attributes.get("data-id") or ""
            if not (m and title and jid):
                continue
            company = node_text(card.css_first("a[offer-grid-article-company-url]"))
            where = node_text(card.css_first("p span.mr10"))
            stubs.append(
                JobStub(
                    source=self.name,
                    url=m[0],
                    title=title,
                    company=company or "Confidencial",
                    location=where,
                    ats=self.name,
                    apply_url=m[0],
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
