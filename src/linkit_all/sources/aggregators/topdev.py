"""TopDev (topdev.vn), a Vietnamese IT job board. Its search results are drawn by the page's own
script after load (the served HTML holds only promoted rails, and no API is exposed), so the
search page is opened in the app's headless Chrome (`PageBrowser`), which stops at any bot
challenge and never passes one. Cards carry a relative age ("3 ngày trước"); no body.
Logic adapted from career-ops (MIT, scan-topdev.mjs)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from urllib.parse import urlencode

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.browser_extract import PageBrowser
from linkit_all.sources.common import absolute, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import node_text
from linkit_all.sources.tasks import fresh, limited, query_tasks
from linkit_all.sources.text import html_to_text

SEARCH = "https://topdev.vn/jobs/search"
MAX_PAGES = 5
REGIONS = {
    "ho chi minh": "79", "hồ chí minh": "79", "hcm": "79", "saigon": "79",
    "hanoi": "01", "ha noi": "01", "hà nội": "01", "da nang": "48", "đà nẵng": "48",
}  # fmt: skip
_POSTING = re.compile(r"^https://topdev\.vn/detail-jobs/[^?#]*?-(\d+)")
_AGE = re.compile(
    r"^(\d+)\s*(minutes?|min|hours?|days?|weeks?|months?|phút|giờ|ngày|tuần|tháng)(?:\s|$)"
)
_UNIT = {
    "phút": "minutes", "min": "minutes", "giờ": "hours", "ngày": "days", "tuần": "weeks",
    "tháng": "months",
}  # fmt: skip


def age(text: str, now: datetime | None = None) -> datetime | None:
    """ "3 ngày trước" / "2 hours ago" / "vừa xong" as naive UTC."""
    now, t = now or utcnow(), text.strip().lower()
    if t in ("vừa xong", "just now", "vừa đăng"):
        return now
    m = _AGE.match(t)
    if not m:
        return None
    unit = _UNIT.get(m[2], m[2].rstrip("s") + "s")
    if unit == "months":
        return now - timedelta(days=30 * int(m[1]))
    return now - timedelta(**{unit: int(m[1])})


class TopDev(Source):
    name = "topdev"
    kind = "aggregator"

    def __init__(self) -> None:
        self.browser = PageBrowser()

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg)

    async def aclose(self) -> None:
        await self.browser.close()

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        region = REGIONS.get(task.location.strip().lower(), "")
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            query = {
                "keyword": task.query,
                "page": page,
                **({"region_ids": region} if region else {}),
            }
            capture = await self.browser.capture(http, f"{SEARCH}?{urlencode(query)}")
            stubs = fresh(self.cards(capture.html), seen)
            if not stubs:
                return
            yield stubs

    def cards(self, html: str) -> list[JobStub]:
        stubs = []
        for card in LexborHTMLParser(html).css('div[class*="text-card-foreground"]'):
            link = card.css_first('a[href*="/detail-jobs/"]')
            url = absolute(link.attributes.get("href") if link else "", "https://topdev.vn/")
            m, title = _POSTING.match(url), node_text(link)
            if not (m and title):
                continue
            company = node_text(link.parent.css_first("span")) if link and link.parent else ""
            grid = card.css_first('div[class*="grid-cols-2"]')
            cells = [node_text(c) for c in grid.css("span.line-clamp-1")] if grid else []
            where = cells[0] if cells else ""
            stubs.append(
                JobStub(
                    source=self.name,
                    url=url.split("?")[0],
                    title=title,
                    company=company or "TopDev",
                    location=where,
                    posted_at=age(cells[-1]) if len(cells) >= 3 else None,
                    ats=self.name,
                    apply_url=url.split("?")[0],
                    remote=remote_from_text(where, title),
                    extra={"id": m[1], "level": cells[1] if len(cells) >= 2 else ""},
                )
            )
        return stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        body = html_to_text(str(found[0].get("description") or "")) if found else ""
        return stub.model_copy(update={"description": body}) if body else stub
