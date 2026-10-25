"""JobiDanmark (jobdanmark.dk), a Danish job portal. Its search API lists jobs without a body;
`fetch_details` reads each job page's schema.org JobPosting. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from datetime import datetime
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import all_older, feed_task
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import absolute
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.text import html_to_text

BASE = "https://jobdanmark.dk"
SEARCH = BASE + "/api/jobsearch/search/{}"
PAGE = 30  # what the API serves per page
BODY = {"jobTypes": [], "filters": [], "locationMode": "Text", "distance": 50}  # no filter


class JobDanmark(Source):
    name = "jobdanmark"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, ceil(task.limit / PAGE) + 1):
            data = await http.post_json(SEARCH.format(page), BODY)
            rows = data.get("items") or []
            if not rows:
                return
            stubs = [s for r in rows if (s := self.stub(r))]
            if stubs:
                yield stubs
            if page >= data.get("totalPages", 0) or all_older(stubs, task):
                return

    def stub(self, it: dict[str, Any]) -> JobStub | None:
        path = (it.get("url") or "").split("?")[0].split("#")[0].rstrip("/")
        if not (path and it.get("title") and it.get("companyName")):
            return None
        url = absolute(path, BASE)  # the slug (last segment) stays recoverable from the url
        try:  # the list date is DD-MM-YYYY
            posted = datetime.strptime(it.get("publishedDate") or "", "%d-%m-%Y")
        except ValueError:
            posted = None
        return JobStub(
            source=self.name,
            url=url,
            title=it["title"].strip(),
            company=it["companyName"].strip(),
            location=", ".join(p for p in (it.get("companyAddress"), "Danmark") if p),
            posted_at=posted,
            apply_url=url,
            ats=self.name,
            extra={"id": url.rsplit("/", 1)[-1]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        await http.allowed(stub.url)
        resp = await http.get(stub.url)
        resp.raise_for_status()
        if not (postings := job_postings(resp.text)):
            return stub
        p = postings[0]
        update: dict[str, Any] = {"description": html_to_text(p.get("description") or "")}
        if posted := from_iso(p.get("datePosted")):
            update["posted_at"] = posted
        return stub.model_copy(update=update)
