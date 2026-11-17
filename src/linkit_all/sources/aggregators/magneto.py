"""Magneto365 (magneto365.com), a general job board for Colombia. No public API: the search
pages are server-rendered, 20 cards each (title link, "company | contract" heading, pay, city).
One task per search query. Logic adapted from career-ops (MIT)."""

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

SEARCH = "https://www.magneto365.com/co/trabajos/buscar/{slug}"
MAX_PAGES = 20
_POSTING = re.compile(
    r"^https://(?:www\.)?magneto365\.com/[a-z]{2}/empleos/[a-z0-9-]+-(\d+)/?$", re.I
)
_HIDDEN = re.compile(r"^(?:confidencial|empresa confidencial|magneto(?: empleos| 365)?)$", re.I)


class Magneto(Source):
    name = "magneto"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        slug = re.sub(r"[^\w]+", "-", task.query.strip().lower()).strip("-")
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = SEARCH.format(slug=slug) + (f"?paginator[page]={page}" if page > 1 else "")
            stubs = fresh(self.cards((await get_page(http, url)).text), seen)
            if not stubs:  # past the end, or a page that repeats the last one
                return
            yield stubs

    def cards(self, html: str) -> list[JobStub]:
        stubs = []
        for card in LexborHTMLParser(html).css("article"):
            link = card.css_first("h2 a[href]") or card.css_first("a[href]")
            url = absolute(
                link.attributes.get("href") if link else "", "https://www.magneto365.com/"
            )
            m = _POSTING.match(url)
            title = node_text(link) or (link.attributes.get("title") or "" if link else "")
            if not m or len(title) < 3:
                continue
            named = node_text(card.css_first("h3")).split(" | ")[0].strip()
            lines = [t for p in card.css("p") if (t := node_text(p))]
            where = lines[-1] if lines and not lines[-1].startswith("$") else ""
            stubs.append(
                JobStub(
                    source=self.name,
                    url=url,
                    title=title,
                    company="Confidencial" if not named or _HIDDEN.match(named) else named,
                    location=where,
                    ats=self.name,
                    apply_url=url,
                    remote=remote_from_text(where, title),
                    extra={"id": m[1]},
                )
            )
        return stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        body = html_to_text(str(found[0].get("description") or "")) if found else ""
        return stub.model_copy(update={"description": body}) if body else stub
