"""HigherEdJobs (www.higheredjobs.com), US academic and university jobs, through its public RSS
category feed (category 68, Higher Education). An item's description is "Institution (City,
ST)". On some networks the feed sits behind a bot wall that answers 200 with a challenge page:
that is reported as an error, never read as an empty board, and never solved.
Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, feed_items, rfc_date
from linkit_all.sources.tasks import feed_task

FEED = "https://www.higheredjobs.com/rss/categoryFeed.cfm?catID=68"
_ID = re.compile(r"[?&]JobCode=(\d+)", re.I)


def split_org(text: str) -> tuple[str, str]:
    """ "Northwind College (Austin, TX)" -> ("Northwind College", "Austin, TX")."""
    head, sep, tail = text.rpartition(" (")
    if not sep or not tail.endswith(")"):
        return text, ""
    return head.strip(), tail[:-1].strip()


class HigherEdJobs(Source):
    name = "higheredjobs"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the feed is not paged
            return
        xml = (await get_page(http, FEED)).text
        if "<rss" not in xml[:2000].lower() and "<channel" not in xml.lower():
            raise ValueError("higheredjobs: the answer is not a feed (a bot wall, say)")
        stubs = self.parse(xml)[: task.limit]
        if stubs:
            yield stubs

    def parse(self, xml: str) -> list[JobStub]:
        stubs = []
        for item in feed_items(xml):
            link = item.get("link", "").strip()
            title = clean(item.get("title"))
            company, where = split_org(clean(item.get("description")))
            if not (title and company and link.startswith("https://www.higheredjobs.com/")):
                continue
            jid = _ID.search(link)
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link,
                    title=title,
                    company=company,
                    location=where,
                    posted_at=rfc_date(item.get("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote=remote_from_text(where, title),
                    extra={"id": jid[1] if jid else link},
                )
            )
        return stubs
