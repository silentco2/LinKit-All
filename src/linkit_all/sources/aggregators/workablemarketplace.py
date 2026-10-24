"""Workable's job marketplace (jobs.workable.com): a keyless JSON search over the postings that
employers published to the marketplace, descriptions included. It also lists employers that have no
apply.workable.com board (see workable.py for those). Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f13 import mode
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://jobs.workable.com/api/v1/jobs"
MAX_PAGES = 100  # backstop for a feed that never stops handing back a token
_BODY = ("description", "requirementsSection", "benefitsSection")


class WorkableMarketplace(Source):
    """Opt-in: list `workablemarketplace` under `sources.enabled`; it runs once per query and
    location of the search config."""

    name = "workablemarketplace"
    kind = "aggregator"
    priority = 3  # the employer's own board (workable.py) is the better copy of a duplicate

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        s = cfg.search
        return [
            Task(
                self.name,
                f"{self.name}:{q}|{loc}",
                query=q,
                location=loc,
                limit=s.max_results_per_query,
                posted_within_days=s.posted_within_days,
            )
            for q in s.queries
            for loc in s.locations
        ]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        since = utcnow() - timedelta(days=task.posted_within_days)
        params: dict[str, str] = {"query": task.query}
        if task.location:
            params["location"] = task.location
        token, seen = "", 0
        # Pages chain by an opaque token, so a resume walks the earlier pages again, unyielded.
        for page in range(MAX_PAGES):
            data = await http.get_json(
                API, params={**params, "pageToken": token} if token else params
            )
            jobs = data.get("jobs") or []
            seen += len(jobs)
            if page >= start_page:
                live = [j for j in jobs if j.get("state") == "published" and j.get("id")]
                yield [
                    s for j in live if (s := self.stub(j)).posted_at is None or s.posted_at >= since
                ]
            token = data.get("nextPageToken") or ""
            if not jobs or not token or seen >= task.limit:
                return

    @staticmethod
    def stub(j: dict[str, Any]) -> JobStub:
        loc = j.get("location") or {}
        place = (loc.get("city"), loc.get("subregion"), loc.get("countryName"))
        location = ", ".join(p for p in place if p)
        body = (html_to_text(j.get(k) or "") for k in _BODY)
        return JobStub(
            source="workablemarketplace",
            url=j["url"],
            title=" ".join((j.get("title") or "").split()),
            company=(j.get("company") or {}).get("title") or "Unknown",
            location=location,
            description="\n\n".join(b for b in body if b),
            posted_at=from_iso(j.get("created")),
            ats="workable",
            apply_url=j["url"],
            remote=mode(j.get("workplace")) or remote_from_text(location),
            extra={
                "id": j["id"],
                "company_id": (j.get("company") or {}).get("id"),
                "employment": j.get("employmentType"),
                "department": j.get("department"),
            },
        )
