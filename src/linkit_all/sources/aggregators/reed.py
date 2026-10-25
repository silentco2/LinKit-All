"""Reed job search API (reed.co.uk), the UK's largest job board. Needs a free API key (Setup →
API keys), sent as the HTTP Basic user name. The list has no full text, so descriptions come from
`fetch_details`, which the pipeline runs only for jobs it has not stored yet (Reed limits calls per
hour). Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators.keys import KeyGetter, get_keys, split_location
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

SEARCH_URL = "https://www.reed.co.uk/api/1.0/search"
JOB_URL = "https://www.reed.co.uk/api/1.0/jobs/"
PAGE_SIZE = 100  # the API's maximum
MAX_SKIP = 5000  # per query
_ID = re.compile(r"/(\d+)/?$")


def _date(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value or "", "%d/%m/%Y")
    except ValueError:
        return None


def parse_job(item: dict[str, Any]) -> JobStub | None:
    job_id, employer = item.get("jobId"), (item.get("employerName") or "").strip()
    if not job_id or not employer:
        return None
    location = item.get("locationName") or ""
    title = " ".join(str(item.get("jobTitle") or "").split())
    return JobStub(
        source="reed",
        url=item.get("jobUrl") or f"https://www.reed.co.uk/jobs/{job_id}",
        title=title,
        company=employer,
        location=location,
        posted_at=_date(item.get("date") or item.get("datePosted")),
        remote=remote_from_text(title, location),
        ats="reed",
        extra={"id": str(job_id)},
    )


class Reed(Source):
    name = "reed"
    kind = "aggregator"
    parallel = 1

    def __init__(self, keys: KeyGetter | None = None) -> None:
        self._keys = keys

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        if get_keys(self._keys, self.name, ("api_key",)) is None:
            return []
        return [
            Task(
                self.name,
                f"reed:{query}:{location}",
                query=query,
                location=location,
                limit=cfg.search.max_results_per_query,
                posted_within_days=cfg.search.posted_within_days,
            )
            for query in cfg.search.queries
            for location in cfg.search.locations
        ]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        code, place = split_location(task.location)
        if code and code != "gb":
            raise Unsupported("Reed lists UK jobs only")
        keys = get_keys(self._keys, self.name, ("api_key",))
        if keys is None:
            return
        params: dict[str, Any] = {"keywords": task.query, "resultsToTake": PAGE_SIZE}
        if place:
            params["locationName"] = place
        skip = start_page * PAGE_SIZE
        while skip < MAX_SKIP:
            data = await http.get_json(
                SEARCH_URL,
                params={**params, "resultsToSkip": skip},
                auth=(keys["api_key"], ""),
            )
            results = data.get("results") or []
            if not results:
                return
            yield [s for r in results if (s := parse_job(r))]
            skip += PAGE_SIZE
            if skip >= (data.get("totalResults") or 0) or skip >= task.limit:
                return

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        keys = get_keys(self._keys, self.name, ("api_key",))
        m = _ID.search(stub.url)
        if keys is None or not m:
            return stub
        data = await http.get_json(JOB_URL + m.group(1), auth=(keys["api_key"], ""))
        return stub.model_copy(
            update={
                "description": strip_html(data.get("jobDescription") or ""),
                "apply_url": data.get("externalUrl") or stub.url,
            }
        )
