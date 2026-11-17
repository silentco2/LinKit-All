"""Job Bank (www.jobbank.gc.ca), the Government of Canada's job search, through its public search
feed (Atom, despite "RSS" in the path): 100 entries a page, one task per search query. The
employer and place sit in the entry summary as "<strong>Employer:</strong> ..." lines. The site
asks for 5 seconds between requests (robots.txt Crawl-delay, which Http applies).
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urlencode

from lxml import etree

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, last_segment, safe_date
from linkit_all.sources.tasks import limited, query_tasks
from linkit_all.sources.text import html_to_text

FEED = "https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed"
PAGE = 100
MAX_PAGES = 20
# Hardened: no entity resolution, no network; a feed is third-party text.
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=True)


def summary_field(summary: str, label: str) -> str:
    m = re.search(rf"<strong>{label}:</strong>\s*(.*?)\s*(?:<br\s*/?>|$)", summary, re.I | re.S)
    return clean(html_to_text(m[1])) if m else ""


def _text(entry: etree._Element, tag: str) -> str:
    node = entry.find(f"{{*}}{tag}")
    return "".join(str(t) for t in node.itertext()).strip() if node is not None else ""


class JobBankCa(Source):
    name = "jobbankca"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            query = {"searchstring": task.query, "locationstring": "", "page": page}
            stubs, count = self.parse((await get_page(http, f"{FEED}?{urlencode(query)}")).text)
            if not count:
                return
            yield stubs
            if count < PAGE:
                return

    def parse(self, xml: str) -> tuple[list[JobStub], int]:
        """(stubs, how many entries the page held)."""
        root = etree.fromstring(xml.encode("utf-8"), _PARSER)
        entries = list(root.iter("{*}entry")) if root is not None else []
        stubs = []
        for entry in entries:
            links = entry.findall("{*}link")
            link = next(
                (x for x in links if x.get("rel") == "alternate"), links[0] if links else None
            )
            url = (link.get("href") or "").strip().split(";")[0] if link is not None else ""
            title, summary = clean(_text(entry, "title")), _text(entry, "summary")
            company = summary_field(summary, "Employer")
            if not (title and company and url.startswith("https://www.jobbank.gc.ca/")):
                continue
            where = summary_field(summary, "Location")
            stubs.append(
                JobStub(
                    source=self.name,
                    url=url,
                    title=title,
                    company=company,
                    location=where,
                    description=html_to_text(summary),
                    posted_at=safe_date(_text(entry, "updated")),
                    ats=self.name,
                    apply_url=url,
                    remote=remote_from_text(where),
                    extra={"id": last_segment(url)},
                )
            )
        return stubs, len(entries)
