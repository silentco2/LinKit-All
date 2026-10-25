"""Working Nomads (workingnomads.com), a remote-only jobs aggregator; one public feed of the
recent postings with the body inline. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

FEED = "https://www.workingnomads.com/api/exposed_jobs/"
_ID = re.compile(r"/(\d+)/?$")  # the feed has no id field; it ends the job URL


class WorkingNomads(Source):
    name = "workingnomads"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page:  # one request, one page
            return
        stubs = []
        for r in await http.get_json(FEED):
            m = _ID.search(r.get("url") or "")
            if m and r.get("company_name") and r.get("title"):
                stubs.append(
                    JobStub(
                        source=self.name,
                        url=r["url"],
                        title=r["title"].strip(),
                        company=r["company_name"].strip(),
                        location=r.get("location") or "",
                        description=strip_html(r.get("description") or ""),
                        posted_at=from_iso(r.get("pub_date")),
                        apply_url=r["url"],
                        remote="remote",  # the site lists remote jobs only
                        extra={"id": m[1]},
                    )
                )
        if stubs:
            yield stubs[: task.limit]
