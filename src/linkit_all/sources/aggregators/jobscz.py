"""jobs.cz, Czechia's largest job portal (Alma Career). Keyword search over the public /prace/
listing pages, 30 cards a page; a page past the last redirects back, so the walk stops at the
stated total. Card dates are Czech ("12. října", "Přidáno včera"). Cards have no body:
`fetch_details` reads the posting page's JobPosting data. Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import clean, node_text
from linkit_all.sources.tasks import limited, query_tasks
from linkit_all.sources.text import html_to_text

SEARCH = "https://www.jobs.cz/prace/"
JOB = "https://www.jobs.cz/rpd/{}/"
PAGE = 30
MAX_PAGES = 10
MONTHS = (
    "ledna", "února", "března", "dubna", "května", "června",
    "července", "srpna", "září", "října", "listopadu", "prosince",
)  # fmt: skip
_DAY_MONTH = re.compile(r"^(\d{1,2})\.\s*(\w+)$")
_AGO = re.compile(r"^Aktualizováno před (\d+) (minut|hodin)")
_TOTAL = re.compile(r"Našli jsme\s+([\d\s]+?)\s*nabíd")


def posted(text: str, now: datetime | None = None) -> datetime | None:
    """A card's Czech date as naive UTC; the day-month form is this year, or last year when
    that would be in the future."""
    now = now or utcnow()
    if m := _DAY_MONTH.match(text):
        if m[2] not in MONTHS:
            return None
        when = datetime(now.year, MONTHS.index(m[2]) + 1, int(m[1]))
        return when if when <= now else when.replace(year=now.year - 1)
    if text == "Přidáno dnes":
        return now
    if text == "Přidáno včera":
        return now - timedelta(days=1)
    if m := _AGO.match(text):
        return now - timedelta(**{"minutes" if m[2] == "minut" else "hours": int(m[1])})
    return None


class JobsCz(Source):
    name = "jobscz"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = f"{SEARCH}?q%5B%5D={task.query}" + (f"&page={page}" if page > 1 else "")
            html = (await get_page(http, url)).text
            stubs, total = self.parse(html)
            if total == 0:
                return
            yield stubs
            if page * PAGE >= total:
                return

    def parse(self, html: str) -> tuple[list[JobStub], int]:
        tree = LexborHTMLParser(html)
        cards = tree.css("article.SearchResultCard")
        text = node_text(tree.body)
        if not cards:
            if "Nenašli jsme žádné nabídky" in text:
                return [], 0
            raise ValueError("jobscz: no result cards and no empty-result notice (markup changed?)")
        found = _TOTAL.search(text)
        if not found:
            raise ValueError("jobscz: no result count (markup changed?)")
        stubs = []
        for card in cards:
            # The attributes sit on the card itself or on an element inside it.
            holder = (
                card if "data-jobad-id" in card.attributes else card.css_first("[data-jobad-id]")
            )
            title_node = (
                card if "data-test-ad-title" in card.attributes
                else card.css_first("[data-test-ad-title]")
            )  # fmt: skip
            jid = holder.attributes.get("data-jobad-id") if holder else None
            title = clean(title_node.attributes.get("data-test-ad-title")) if title_node else ""
            company = node_text(card.css_first('span[translate="no"]'))
            if not (jid and jid.isdigit() and title and company):
                continue
            where = node_text(card.css_first('[data-test="serp-locality"]'))
            stubs.append(
                JobStub(
                    source=self.name,
                    url=JOB.format(jid),
                    title=title,
                    company=company,
                    location=where,
                    posted_at=posted(node_text(card.css_first("[data-test-ad-status]"))),
                    ats=self.name,
                    apply_url=JOB.format(jid),
                    remote=remote_from_text(where),
                    extra={"id": jid},
                )
            )
        return stubs, int(re.sub(r"\D", "", found[1]))

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        body = html_to_text(str(found[0].get("description") or "")) if found else ""
        return stub.model_copy(update={"description": body}) if body else stub
