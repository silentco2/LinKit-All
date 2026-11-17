"""Startup Jobs (startup.jobs), a global startup job board, through its public RSS feed (the
JSON API needs an account and is not used). The feed holds only the newest ~50 postings and has
no company or place fields: the company is the title's last " at {Company}" (a row with none is
dropped), the place is the description's last line. Logic adapted from career-ops (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import body_text, clean, feed_items, last_segment, rfc_date
from linkit_all.sources.tasks import feed_task

FEED = "https://startup.jobs/feeds/jobs"
_BEI = re.compile(r"^bei\s+", re.I)  # "... at bei PROLOGA": a German preposition glued on


def title_and_company(raw: str) -> tuple[str, str] | None:
    title, sep, company = raw.rpartition(" at ")
    title, company = title.strip(), _BEI.sub("", company.strip())
    return (title, company) if sep and title and company else None


def place(description: str) -> str:
    """The last non-empty line, without a trailing " · pay range"."""
    lines = [x.strip() for x in description.splitlines() if x.strip()]
    return lines[-1].split(" · ")[0].strip() if lines else ""


class StartupJobs(Source):
    name = "startup-jobs"
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
            link = item.get("link", "").strip().split("?")[0]
            named = title_and_company(clean(item.get("title")))
            if not named or not link.startswith("https://startup.jobs/"):
                continue
            text = body_text(item.get("description", ""))
            where = place(text)
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link,
                    title=named[0],
                    company=named[1],
                    location=where,
                    description=text,
                    posted_at=rfc_date(item.get("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote=remote_from_text(where),
                    extra={"id": last_segment(link)},
                )
            )
        return stubs
