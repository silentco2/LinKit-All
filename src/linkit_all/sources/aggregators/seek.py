"""SEEK (seek.com.au, seek.co.nz), the main job board in Australia and New Zealand. Lists through
the site's own frontend search API; the body comes from its GraphQL `jobDetails`
(`fetch_details`), which meters requests per IP, so the first rate-limit answer stops detail
fetches for the run.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from math import ceil
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators.keys import split_location
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.tasks import all_older, query_tasks

PAGE = 100
MAX_PAGES = 6  # SEEK's result window ends about here
MARKETS = {
    "au": ("https://www.seek.com.au", "AU-Main", "All Australia"),
    "nz": ("https://www.seek.co.nz", "NZ-Main", "All New Zealand"),
}
DETAIL_QUERY = (
    "query jobDetails($jobId: ID!) { jobDetails(id: $jobId) { job { content(platform: WEB) } } }"
)
_JOB_URL = re.compile(r"^(https://www\.seek\.co(?:m\.au|\.nz))/job/(\d+)")
_MODES: dict[str, Remote] = {"remote": "remote", "hybrid": "hybrid", "on-site": "onsite"}


class Seek(Source):
    name = "seek"
    kind = "aggregator"

    def __init__(self) -> None:
        self._details_stopped = False  # set by the first rate-limit answer, for the run

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [
            t
            for t in query_tasks(self.name, cfg)
            if split_location(t.location)[0] in (None, "au", "nz")
        ]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        code, place = split_location(task.location)
        host, site_key, everywhere = MARKETS[code if code in MARKETS else "au"]
        seen: set[str] = set()
        for page in range(start_page + 1, min(MAX_PAGES, ceil(task.limit / PAGE)) + 1):
            params = {"siteKey": site_key, "where": place or everywhere, "keywords": task.query,
                      "page": page, "pageSize": PAGE, "sortmode": "ListedDate"}  # fmt: skip
            data = await http.get_json(f"{host}/api/jobsearch/v5/search", params=params)
            rows = [r for r in data.get("data") or [] if r.get("id") and r["id"] not in seen]
            seen.update(r["id"] for r in rows)
            stubs = [s for r in rows if (s := self.stub(r, host))]
            if stubs:
                yield stubs
            if not rows or all_older(stubs, task):  # empty, repeated tail, or window exhausted
                return

    def stub(self, p: dict[str, Any], host: str) -> JobStub | None:
        company = (
            p.get("companyName") or (p.get("advertiser") or {}).get("description") or ""
        ).strip()
        if not company or company.lower() == "private advertiser" or not p.get("title"):
            return None
        labels = {
            ((a.get("label") or {}).get("text") or "").strip().lower()
            for a in (p.get("workArrangements") or {}).get("data") or []
        }
        mode = next((_MODES[m] for m in ("remote", "hybrid", "on-site") if m in labels), None)
        url = f"{host}/job/{p['id']}"
        places = p.get("locations") or [{}]
        return JobStub(
            source=self.name,
            url=url,  # host and id stay recoverable from the url for fetch_details
            title=p["title"].strip(),
            company=company,
            location=(places[0].get("label") or "").strip(),
            posted_at=from_iso(p.get("listingDate")),
            ats=self.name,
            apply_url=url,
            remote=mode,
            extra={"id": p["id"], "salary": p.get("salaryLabel") or ""},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _JOB_URL.match(stub.url)
        if not m or self._details_stopped:
            return stub
        body = {"operationName": "jobDetails", "query": DETAIL_QUERY, "variables": {"jobId": m[2]}}
        try:
            data = await http.post_json(f"{m[1]}/graphql", body)
        except RetryableStatus as e:
            self._details_stopped = e.response.status_code == 429  # the per-IP budget is spent
            return stub
        except httpx.HTTPError:
            return stub
        if any(
            (e.get("extensions") or {}).get("code") == "RATE_LIMITED"
            for e in data.get("errors") or []
        ):
            self._details_stopped = True  # answered with HTTP 200, so it is easy to miss
            return stub
        content = (((data.get("data") or {}).get("jobDetails") or {}).get("job") or {}).get(
            "content"
        )
        return stub.model_copy(update={"description": strip_html(content)}) if content else stub
