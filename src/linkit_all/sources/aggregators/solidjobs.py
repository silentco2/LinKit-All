"""solid.jobs, a Polish job board split into divisions (IT, ...); the public API returns each
posting with its description. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

API = "https://solid.jobs/public-api/offers/{}"
CAMPAIGN = "linkit"  # the API requires one; it is echoed into every posting URL
DIVISIONS = ("it",)  # ponytail: add more division slugs here when someone needs them


def _mode(o: dict[str, Any]) -> Remote:
    return "remote" if o.get("isRemote") else "hybrid" if o.get("isHybrid") else "onsite"


class SolidJobs(Source):
    name = "solidjobs"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [
            replace(t, key=f"{self.name}:{d}", board=d)
            for d in DIVISIONS
            for t in feed_task(self.name, cfg)
        ]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        # One page of (at most) 500 postings per division: the API's own page index cannot be
        # followed, so there is nothing to resume.
        if start_page:
            return
        data = await http.get_json(API.format(task.board), params={"campaign": CAMPAIGN})
        stubs = [s for o in data.get("jobs") or [] if (s := self.stub(o))]
        if stubs:
            yield stubs[: task.limit]

    def stub(self, o: dict[str, Any]) -> JobStub | None:
        if not o.get("jobOfferKey") or not o.get("company") or not o.get("title"):
            return None
        body = strip_html(o.get("description") or "")
        skills = [s["name"] for s in o.get("skills") or [] if s.get("name")]
        if skills:
            body = f"{body}\n\nSkills: {', '.join(skills)}".strip()
        return JobStub(
            source=self.name,
            url=o.get("url") or f"https://solid.jobs/o/{o['jobOfferKey']}",
            title=o["title"].strip(),
            company=o["company"].strip(),
            location=", ".join(loc for loc in o.get("locations") or [] if loc),
            description=body,
            posted_at=from_iso(o.get("validFrom")),
            apply_url=o.get("url"),
            remote=_mode(o),
            extra={"id": o["jobOfferKey"]},
        )
