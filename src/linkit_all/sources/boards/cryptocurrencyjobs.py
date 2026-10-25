"""Cryptocurrency Jobs (cryptocurrencyjobs.co), a Web3 and crypto jobs board: its RSS feed lists
the newest postings ("Title at Company"); the full description comes from the posting page's
JobPosting block (`fetch_details`). Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import get_page, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import body_text, feed_items, rfc_date
from linkit_all.sources.tasks import feed_task

FEED = "https://cryptocurrencyjobs.co/index.xml"
# A title ending "(Berlin only)" is an on-site role in that place; all others are remote.
_ONSITE = re.compile(r"\s*\(([^()]+?)\s+only\)\s*$")


class CryptocurrencyJobs(Source):
    name = "cryptocurrencyjobs"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the feed is not paged
            return
        stubs = []
        for item in feed_items((await get_page(http, FEED)).text):
            link, guid = item.get("link", "").strip(), item.get("guid", "").strip()
            title, sep, company = item.get("title", "").partition(" at ")
            if not (guid and link and sep and company.strip()):
                continue
            location: str = "Remote"
            remote: Remote = "remote"
            if m := _ONSITE.search(title):
                location, remote, title = m[1], "onsite", title[: m.start()]
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link,
                    title=title.strip(),
                    company=company.strip(),
                    location=location,
                    description=body_text(item.get("description", "")),
                    posted_at=rfc_date(item.get("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote=remote,
                    extra={"id": guid},
                )
            )
        yield stubs[: task.limit]

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        """The feed's description is a teaser; the page's JobPosting block has the whole text."""
        postings = job_postings((await get_page(http, stub.url)).text)
        text = strip_html((postings[0].get("description") or "") if postings else "", escaped=True)
        return stub.model_copy(update={"description": text}) if text else stub
