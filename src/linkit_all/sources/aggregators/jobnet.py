"""Jobnet.dk, Denmark's official public job portal. Its search API (the one the site's own front
end calls, with the plain `x-csrf: 1` header it sends) carries every body. Logic adapted from
freehire (MIT)."""

from collections.abc import AsyncIterator
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import all_older, feed_task
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

API = "https://jobnet.dk/bff/FindJob/Search"
JOB_URL = "https://job.jobnet.dk/CV/FindWork/Details/{}"
PAGE = 100


class Jobnet(Source):
    name = "jobnet"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen = start_page * PAGE
        for page in range(start_page + 1, ceil(task.limit / PAGE) + 1):
            data = await http.get_json(
                API,
                params={"PageNumber": page, "ResultsPerPage": PAGE, "OrderType": "PublicationDate"},
                headers={"x-csrf": "1"},
            )
            rows = data.get("jobAds") or []
            if not rows:
                return
            seen += len(rows)
            stubs = [s for r in rows if (s := self.stub(r))]
            if stubs:
                yield stubs
            if seen >= data.get("totalJobAdCount", 0) or all_older(stubs, task):
                return

    def stub(self, a: dict[str, Any]) -> JobStub | None:
        if not (a.get("jobAdId") and a.get("hiringOrgName") and a.get("title")):
            return None
        page = JOB_URL.format(a["jobAdId"])  # the id stays recoverable from the url
        location = ", ".join(p for p in (a.get("postalDistrictName"), a.get("country")) if p)
        return JobStub(
            source=self.name,
            url=page,
            title=a["title"].strip(),
            company=a["hiringOrgName"].strip(),
            location=location,
            description=strip_html(a.get("description") or ""),
            posted_at=from_iso(a.get("publicationDate")),
            apply_url=a.get("jobAdUrl") or page,  # external ads carry their own destination
            remote=remote_from_text(location),
            ats=self.name,
            extra={"id": a["jobAdId"]},
        )
