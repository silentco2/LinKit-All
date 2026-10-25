"""No Fluff Jobs (nofluffjobs.com), a Polish and Central European IT job board. The one public
listing (a large document) has no body, so `fetch_details` reads each posting's own endpoint.
Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

LIST = "https://nofluffjobs.com/api/posting"
DETAIL = "https://nofluffjobs.com/api/posting/{}"
JOB_URL = "https://nofluffjobs.com/job/{}"
PAGE = 100
PERIODS = {"hour": "hour", "day": "day", "month": "month", "year": "year"}


class NoFluffJobs(Source):
    name = "nofluffjobs"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        # ponytail: the whole listing is read into memory (tens of MB); stream it if that bites
        data = await http.get_json(LIST)
        cutoff = utcnow() - timedelta(days=task.posted_within_days)
        stubs = [s for p in data.get("postings") or [] if (s := self.stub(p))]
        stubs = sorted(
            (s for s in stubs if s.posted_at is None or s.posted_at >= cutoff),
            key=lambda s: s.posted_at or cutoff,
            reverse=True,
        )[: task.limit]
        for i in range(start_page * PAGE, len(stubs), PAGE):
            yield stubs[i : i + PAGE]

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        company = (p.get("name") or "").strip()
        if not (p.get("id") and p.get("url") and company and (p.get("title") or "").strip()):
            return None
        loc = p.get("location") or {}
        remote = bool(loc.get("fullyRemote"))  # the posting-level flag is false on every row
        stub = JobStub(
            source=self.name,
            url=JOB_URL.format(p["url"]),  # the slug stays recoverable from the url
            title=p["title"].strip(),
            company=company,
            location=self.location(loc),
            posted_at=from_epoch_ms(p.get("posted")),
            ats=self.name,
            apply_url=JOB_URL.format(p["url"]),
            remote="remote" if remote else None,
            extra={"id": p["id"], "slug": p["url"]},
        )
        pay = p.get("salary") or {}
        period = PERIODS.get(str(pay.get("period") or "").lower())
        if pay.get("containsSalary") == "VISIBLE" and period and pay.get("currency"):
            stub.salary_min, stub.salary_max = pay.get("from"), pay.get("to")
            stub.salary_currency, stub.salary_interval = pay["currency"], period
        return stub

    @staticmethod
    def location(loc: dict[str, Any]) -> str:
        """The first real place as "City, Country". A remote posting lists a countryless "Remote"
        pseudo-place ahead of its offices: skipped, so it does not hide the country."""
        for place in loc.get("places") or []:
            country = (place.get("country") or {}).get("name") or ""
            city = (place.get("city") or "").strip()
            if not country and city.lower() == "remote":
                continue
            if label := ", ".join(x for x in (city, country.strip()) if x):
                return label
        return "Remote" if loc.get("fullyRemote") else ""

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        slug = stub.url.rsplit("/job/", 1)[-1]
        d = await http.get_json(DETAIL.format(slug))
        parts = [
            (d.get("details") or {}).get("description"),
            (d.get("requirements") or {}).get("description"),
        ]
        return stub.model_copy(update={"description": strip_html("\n".join(p for p in parts if p))})
