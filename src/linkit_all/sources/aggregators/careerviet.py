"""CareerViet (careerviet.vn), a broad Vietnamese job board. Search pages are server-rendered
cards ("{keyword}-k-vi.html", then "-trang-N-vi.html"); each card carries its last update date
(day-month-year, Vietnam time). Cards have no body: `fetch_details` reads the posting page's
JobPosting data. Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from urllib.parse import quote

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import absolute, get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import node_text
from linkit_all.sources.tasks import fresh, limited, query_tasks
from linkit_all.sources.text import html_to_text

BASE = "https://careerviet.vn/viec-lam"
MAX_PAGES = 50
_DATE = re.compile(r"(\d{1,2})[-/](\d{1,2})[-/](\d{4})")


def list_url(query: str, page: int) -> str:
    words = re.sub(r"\s+", "-", query.strip().lower())
    slug = f"{quote(words, safe='-')}-k" if words else "tat-ca-viec-lam"
    return f"{BASE}/{slug}{'-vi.html' if page <= 1 else f'-trang-{page}-vi.html'}"


def updated(text: str) -> datetime | None:
    """ "26-08-2026" (Vietnam, UTC+7, midnight) as naive UTC."""
    m = _DATE.search(text)
    try:
        return datetime(int(m[3]), int(m[2]), int(m[1])) - timedelta(hours=7) if m else None
    except ValueError:
        return None


class CareerViet(Source):
    name = "careerviet"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            stubs = fresh(self.cards((await get_page(http, list_url(task.query, page))).text), seen)
            if not stubs:
                return
            yield stubs

    def cards(self, html: str) -> list[JobStub]:
        stubs = []
        for card in LexborHTMLParser(html).css('[id^="job-item-"]'):
            jid = (card.attributes.get("id") or "").removeprefix("job-item-")
            link = card.css_first("a.job_link")
            url = absolute(link.attributes.get("href") if link else "", "https://careerviet.vn/")
            title = ((link.attributes.get("title") or "") if link else "").strip() or node_text(
                link
            )
            company_link = card.css_first("a.company-name")
            company = ((company_link.attributes.get("title") or "") if company_link else "").strip()
            if not (jid and title and company and url.startswith("https://careerviet.vn/")):
                continue
            where = node_text(card.css_first("div.location li"))
            stubs.append(
                JobStub(
                    source=self.name,
                    url=url.split("?")[0],
                    title=title,
                    company=company,
                    location=where,
                    posted_at=updated(node_text(card.css_first("time"))),
                    ats=self.name,
                    apply_url=url,
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
