"""Rheinmetall's vacancy list (www.rheinmetall.com/en/career/vacancies): a Nuxt page with server-
rendered cards (about 10 a page, `?page=N`). A card reads "{Company GmbH} | {City}", so the group
company is the employer. No date on the cards; the posting page's JobPosting data gives the
body. Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import node_text
from linkit_all.sources.tasks import careers_task, fresh, limited
from linkit_all.sources.text import html_to_text

LIST = "https://www.rheinmetall.com/en/career/vacancies"
ORIGIN = "https://www.rheinmetall.com"
MAX_PAGES = 200
MAX_JOBS = 1500
_JOB = re.compile(r"^/[a-z]{2}/job/[^/]+/(\d+)$")


class Rheinmetall(Source):
    name = "rheinmetall"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, start_page), MAX_JOBS):
            yield page

    async def _pages(self, http: Http, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            stubs = fresh(self.cards((await get_page(http, f"{LIST}?page={page}")).text), seen)
            if not stubs:  # past the end
                return
            yield stubs

    def cards(self, html: str) -> list[JobStub]:
        stubs = []
        for card in LexborHTMLParser(html).css("div.group"):
            link = next(
                (a for a in card.css("a[href]") if _JOB.match(a.attributes.get("href") or "")),
                None,
            )
            title = node_text(card.css_first('div[class*="md:text-xl"]'))
            if link is None or not title:
                continue
            path = str(link.attributes.get("href"))
            org = node_text(card.css_first("div.flex-wrap.mr-6"))
            company, _, city = org.rpartition("|") if "|" in org else (org, "", "")
            m = _JOB.match(path)
            stubs.append(
                JobStub(
                    source=self.name,
                    url=ORIGIN + path,
                    title=title,
                    company=company.strip() or "Rheinmetall",
                    location=city.strip(),
                    ats=self.name,
                    apply_url=ORIGIN + path,
                    remote=remote_from_text(city, title),
                    extra={"id": m[1] if m else path},
                )
            )
        return stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        body = html_to_text(str(found[0].get("description") or "")) if found else ""
        return stub.model_copy(update={"description": body}) if body else stub
