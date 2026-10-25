"""We Work Remotely (weworkremotely.com), a remote-jobs board: its public RSS feed lists the
newest postings with the description inline. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.ats._f13 import get_page
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.boards._f32 import body_text, feed_items, rfc_date
from linkit_all.sources.http import Http

FEED = "https://weworkremotely.com/remote-jobs.rss"


class WeWorkRemotely(Source):
    name = "weworkremotely"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the feed is not paged
            return
        stubs = []
        for item in feed_items((await get_page(http, FEED)).text):
            link = item.get("link", "").strip()
            company, sep, title = item.get("title", "").partition(": ")  # "Company: Job title"
            slug = link.rstrip("/").rpartition("/")[2]
            if not (slug and sep and company.strip()):
                continue
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link,
                    title=title.strip(),
                    company=company.strip(),
                    location=item.get("region", "") or "Remote",
                    description=body_text(item.get("description", "")),
                    posted_at=rfc_date(item.get("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote="remote",
                    extra={"id": slug},
                )
            )
        yield stubs[: task.limit]
