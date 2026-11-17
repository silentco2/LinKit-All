"""GermanTechJobs (germantechjobs.de), German IT jobs, through its public RSS feed (the old JSON
API is deprecated upstream). A title reads "{Role} @ {Company} [{pay}]"; a row with no " @ "
names no employer and is dropped. The feed has no place field. Logic adapted from career-ops
(MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import body_text, clean, feed_items, last_segment, rfc_date
from linkit_all.sources.tasks import feed_task

FEED = "https://germantechjobs.de/rss"
_PAY = re.compile(r"\s*\[[^\]]*€[^\]]*\]\s*$")


def title_and_company(raw: str) -> tuple[str, str] | None:
    """ "Backend Dev @ Acme GmbH [60k - 80k €]" -> ("Backend Dev", "Acme GmbH")."""
    title, sep, company = _PAY.sub("", raw.strip()).rpartition(" @ ")
    return (title.strip(), company.strip()) if sep and title.strip() and company.strip() else None


class GermanTechJobs(Source):
    name = "germantechjobs"
    kind = "aggregator"

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
            link = (item.get("link") or item.get("guid") or "").strip().split("?")[0]
            named = title_and_company(clean(item.get("title")))
            if not named or not link.startswith("https://germantechjobs.de/"):
                continue
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link,
                    title=named[0],
                    company=named[1],
                    description=body_text(item.get("description", "")),
                    posted_at=rfc_date(item.get("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote=remote_from_text(named[0]),
                    extra={"id": last_segment(link)},
                )
            )
        return stubs
