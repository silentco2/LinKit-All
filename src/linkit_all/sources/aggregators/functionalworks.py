"""Functional Works (functional.works-hub.com), a board for functional-programming and adjacent
engineering roles. One GraphQL query returns the whole backlog with bodies inline.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

API = "https://functional.works-hub.com/api/graphql"
JOB_URL = "https://functional.works-hub.com/jobs/{}"
PAGE = 100
# The endpoint has no offset argument, so page_size just has to exceed the backlog (~900).
QUERY = (
    '{ jobs(page_size:2000, vertical:"functional", published:true) { '
    "title slug remote firstPublished descriptionHtml company { name } "
    "location { city country } tags { label } } }"
)


class FunctionalWorks(Source):
    name = "functionalworks"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        data = await http.post_json(API, {"query": QUERY})
        rows = ((data.get("data") or {}).get("jobs") or [])[: task.limit]
        for i in range(start_page * PAGE, len(rows), PAGE):
            if stubs := [s for r in rows[i : i + PAGE] if (s := self.stub(r))]:
                yield stubs

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        company = (p.get("company") or {}).get("name")
        if not p.get("slug") or not company or not p.get("title"):
            return None
        loc = p.get("location") or {}
        location = ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
        body = strip_html(p.get("descriptionHtml") or "")
        tags = [t["label"] for t in p.get("tags") or [] if t.get("label")]
        if tags:
            body = f"{body}\n\nTags: {', '.join(tags)}".strip()
        url = JOB_URL.format(p["slug"])
        return JobStub(
            source=self.name,
            url=url,
            title=p["title"].strip(),
            company=company,
            location=location,
            description=body,
            posted_at=from_iso(p.get("firstPublished")),
            apply_url=url,
            remote="remote" if p.get("remote") else remote_from_text(location),
            extra={"id": p["slug"]},
        )
