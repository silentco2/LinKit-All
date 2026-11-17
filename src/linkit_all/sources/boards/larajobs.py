"""LaraJobs (larajobs.com), a Laravel and PHP job board. Its public RSS feed names the company
and place in its own `job:` fields; the feed is not paged. Links off larajobs.com are dropped.
Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import body_text, clean, feed_items, last_segment, rfc_date
from linkit_all.sources.tasks import feed_task

FEED = "https://larajobs.com/feed"


class LaraJobs(Source):
    name = "larajobs"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the feed is not paged
            return
        stubs = self.parse((await get_page(http, FEED)).text)[: task.limit]
        if stubs:
            yield stubs

    def parse(self, xml: str) -> list[JobStub]:
        stubs = []
        for item in feed_items(xml):
            link = item.get("link", "").strip()
            title, company = clean(item.get("title")), clean(item.get("company"))
            if not (title and company and link.startswith("https://larajobs.com/")):
                continue
            where = clean(item.get("location"))
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link.split("?")[0],
                    title=title,
                    company=company,
                    location=where,
                    description=body_text(item.get("description", "")),
                    posted_at=rfc_date(item.get("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote=remote_from_text(where),
                    extra={"id": item.get("guid", "").strip() or last_segment(link)},
                )
            )
        return stubs
