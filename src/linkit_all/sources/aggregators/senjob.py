"""Senjob (senjob.com), a Senegalese job board. No API: the listing is a server-rendered table
whose rows link postings as "/jobseekers/{slug}_e_{id}.html" and carry a hidden ISO date. The
list names no employer: `fetch_details` reads it, with the body, from the posting page's
JobPosting data when there is one. Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import clean, node_text, safe_date
from linkit_all.sources.tasks import all_older, feed_task, limited
from linkit_all.sources.text import html_to_text

LIST = "https://senjob.com/offres-d-emploi.php"
MAX_PAGES = 50
_POSTING = re.compile(r"^https://senjob\.com/jobseekers/[^\"?#]*?_e_(\d+)\.html$", re.I)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PUBLISHED = re.compile(r"Publi[ée]", re.I)


class Senjob(Source):
    name = "senjob"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = LIST if page <= 1 else f"{LIST}?page={page}"
            stubs = [s for s in self.rows((await get_page(http, url)).text) if s.url not in seen]
            seen.update(s.url for s in stubs)
            if not stubs:  # a dry page ends the walk
                return
            yield stubs
            if all_older(stubs, task):
                return

    def rows(self, html: str) -> list[JobStub]:
        found: dict[str, JobStub] = {}
        for row in LexborHTMLParser(html).css("tr"):
            link = next(
                (a for a in row.css("a[href]") if _POSTING.match(a.attributes.get("href") or "")),
                None,
            )
            if link is None:
                continue
            url = str(link.attributes.get("href"))
            m, title = _POSTING.match(url), node_text(link)
            if not (m and title) or url in found:
                continue
            rest = node_text(row).split(title, 1)[-1]
            where = clean(_PUBLISHED.split(rest)[0]).strip(" |:-")
            hidden = next(
                (t for s in row.css("span") if _DATE.match(t := node_text(s))
                 and "none" in (s.attributes.get("style") or "")),
                "",
            )  # fmt: skip
            found[url] = JobStub(
                source=self.name,
                url=url,
                title=title,
                company="",  # the list names none; fetch_details fills it when the page does
                location=where,
                posted_at=safe_date(hidden),
                ats=self.name,
                apply_url=url,
                remote=remote_from_text(where, title),
                extra={"id": m[1]},
            )
        return list(found.values())

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        if not found:
            return stub
        org = found[0].get("hiringOrganization")
        company = clean(org.get("name") if isinstance(org, dict) else org)
        body = html_to_text(str(found[0].get("description") or ""))
        update = {"company": company or stub.company, "description": body or stub.description}
        return stub.model_copy(update=update)
