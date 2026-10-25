"""teamex.io, a global talent marketplace; its paged filter endpoint returns whole postings.
Logic adapted from freehire (MIT)."""

import html
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

LIST = "https://api.teamex.io/api/jts/global/filter"
JOB_URL = "https://teamex.io/job/{}"
PAGE = 50
MAX_PAGES = 100  # a runaway guard
ANONYMOUS = "TeamEx"  # the marketplace hides many employers


class Teamex(Source):
    name = "teamex"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        count = 0
        for page in range(start_page + 1, MAX_PAGES + 1):  # pageIndex is 1-based
            body = await http.post_json(LIST, {}, params={"pageSize": PAGE, "pageIndex": page})
            data = body.get("data") or {}
            rows = data.get("data") or []
            if not rows:
                return
            stubs = [self.stub(r) for r in rows if r.get("isActive") and r.get("sequenceId")]
            yield stubs  # even when empty: the page number is the resume checkpoint
            count += len(stubs)
            total = (data.get("paging") or {}).get("totalCount") or 0
            if count >= task.limit or (total and page * PAGE >= total):
                return

    def stub(self, r: dict[str, Any]) -> JobStub:
        # An anonymised posting must not leak the employer even if the payload names it.
        company = ANONYMOUS if r.get("isAnonymous") else (r.get("company") or {}).get("name")
        sections = "".join(
            (f"<h3>{html.escape(d['title'])}</h3>" if (d.get("title") or "").strip() else "")
            + (d.get("content") or "")
            for d in r.get("descriptions") or []
        )
        skills = [
            s["skill"]["displayName"]
            for s in r.get("requiredSkills") or []
            if (s.get("skill") or {}).get("displayName")
        ]
        text = strip_html(sections)
        if skills:
            text = f"{text}\n\nSkills: {', '.join(skills)}".strip()
        url = JOB_URL.format(r["sequenceId"])
        location = ", ".join(c["name"] for c in r.get("countries") or [] if c.get("name"))
        return JobStub(
            source=self.name,
            url=url,
            title=(r.get("title") or "").strip(),
            company=company or ANONYMOUS,
            location=location,
            description=text,
            posted_at=from_iso(r.get("publishedDate")),
            apply_url=url,
            remote=remote_from_text(r.get("title"), location),
            extra={"id": r["sequenceId"]},
        )
