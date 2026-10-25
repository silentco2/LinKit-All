"""Built In (builtin.com), a US-centred tech job board that lists employers' postings worldwide.
Each job family's listing is read for postings updated in the last day, slowly (its edge
challenges a faster pace and we never work around that); the posting page supplies the body.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from aiolimiter import AsyncLimiter
from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import fetch_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import clean, ld_stub
from linkit_all.sources.tasks import feed_task

BASE = "https://builtin.com"
MAX_PAGES = 1000  # the listing's own ceiling
WINDOW_DAYS = 1  # the narrowest "updated within" choice the listing offers
INTERVAL = 2.0  # seconds between requests: slower than the pace at which its edge pushes back
CATEGORIES = (
    "dev-engineering", "data-analytics", "cybersecurity-it", "product", "design-ux",
    "project-management", "operations", "customer-success", "sales", "marketing", "finance",
    "hr", "legal", "content",
)  # fmt: skip
_MODES: dict[str, Remote] = {"Remote": "remote", "Hybrid": "hybrid", "In-Office": "onsite"}
MAX_HOURLY_USD = 500  # above this an "hourly" wage is a yearly figure mislabelled


@dataclass
class Card:
    id: str
    url: str
    title: str
    company: str
    mode: Remote | None


def parse_cards(page: str) -> list[Card]:
    """Job cards of a listing page."""
    out = []
    for node in LexborHTMLParser(page).css('[data-id="job-card"]'):
        company = node.css_first('[data-id="company-title"]')
        title = node.css_first('[data-id="job-card-title"]')
        if company is None or title is None:
            continue
        href = (title.attributes.get("href") or "").strip()
        card = Card(
            id=(title.attributes.get("data-builtin-track-job-id") or "").strip(),
            url=BASE + href if href.startswith("/job/") else "",
            title=clean(title.text(deep=True)),
            company=clean(company.text(deep=True)),
            mode=_MODES.get(_icon_text(node, "i.fa-house-building")),
        )
        if card.id and card.url and card.title and card.company:
            out.append(card)
    return out


def _icon_text(card: LexborNode, selector: str) -> str:
    """The label beside an icon: the first <span> under the icon's grandparent."""
    icon = card.css_first(selector)
    box = icon.parent.parent if icon is not None and icon.parent is not None else None
    span = box.css_first("span") if box is not None else None
    return clean(span.text(deep=True)) if span is not None else ""


class BuiltIn(Source):
    name = "builtin"
    kind = "board"

    def __init__(self) -> None:
        self._pace = AsyncLimiter(1, INTERVAL)

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def _page(self, http: Http, url: str) -> str | None:
        async with self._pace:
            return await fetch_html(http, url)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        listed: set[str] = set()  # a posting filed under two families is one posting
        index = count = 0  # index: pages with news; on resume the skipped ones are re-read
        for cat in CATEGORIES:
            here: set[str] = set()
            for page in range(1, MAX_PAGES + 1):
                url = f"{BASE}/jobs/{cat}?allLocations=true&daysSinceUpdated={WINDOW_DAYS}"
                html = await self._page(http, url + (f"&page={page}" if page > 1 else ""))
                new = [c for c in parse_cards(html or "") if c.url not in here]
                if not new:
                    break  # past the last page the listing answers "No job results"
                here.update(c.url for c in new)
                fresh = [c for c in new if c.id not in listed]
                listed.update(c.id for c in fresh)
                if fresh and index >= start_page:
                    stubs = [self.stub(c) for c in fresh[: task.limit - count]]
                    count += len(stubs)
                    yield stubs
                    if count >= task.limit:
                        return
                index += bool(fresh)

    def stub(self, c: Card) -> JobStub:
        return JobStub(
            source=self.name, url=c.url, title=c.title, company=c.company, apply_url=c.url,
            remote=c.mode, ats=self.name, extra={"id": c.id},
        )  # fmt: skip

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await self._page(http, stub.url)
        found = job_postings(page or "")[:1]
        if not found:
            return stub
        full = ld_stub(
            {**found[0], "title": stub.title}, source=self.name, url=stub.url,
            company=stub.company, extra={},
        )  # fmt: skip
        if full is None:
            return stub
        lo, hi = full.salary_min, full.salary_max
        cur = (full.salary_currency or "").upper()
        usable = bool(lo or hi) and len(cur) == 3 and not (lo and hi and lo > hi)
        usable = usable and not (
            full.salary_interval == "hour"
            and cur == "USD"
            and max(lo or 0, hi or 0) > MAX_HOURLY_USD
        )
        keep: dict[str, Any] = {
            "salary_min": None,
            "salary_max": None,
            "salary_currency": None,
            "salary_interval": None,
        }
        if usable:
            keep = {
                "salary_min": lo, "salary_max": hi, "salary_currency": cur,
                "salary_interval": full.salary_interval,
            }  # fmt: skip
        return stub.model_copy(
            update={
                "description": full.description,
                "location": full.location,
                "posted_at": full.posted_at,
                "company": full.company,
                "remote": stub.remote or full.remote,
                **keep,
            }
        )
