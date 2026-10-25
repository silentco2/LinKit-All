"""USAJobs search API (data.usajobs.gov), the US federal government's job board. Needs a free API
key plus the email it was registered to (Setup → API keys): USAJobs asks for the key in
`Authorization-Key` and that email as the User-Agent. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators.keys import KeyGetter, get_keys, split_location
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http

URL = "https://data.usajobs.gov/api/search"
PAGE_SIZE = 500  # the API's maximum
MAX_PAGES = 50
FIELDS = ("api_key", "email")
_INTERVALS = {"PA": "year", "PH": "hour"}  # other pay-period codes are skipped


def _salary(value: Any) -> float | None:
    try:
        return float(value) or None
    except (TypeError, ValueError):
        return None


def parse_job(item: dict[str, Any]) -> JobStub | None:
    d = item.get("MatchedObjectDescriptor") or {}
    job_id = item.get("MatchedObjectId")
    company = d.get("OrganizationName") or d.get("DepartmentName")
    if not job_id or not company or not d.get("PositionTitle"):
        return None
    det = (d.get("UserArea") or {}).get("Details") or {}
    # "Multiple Locations" says nothing; the first concrete place is a better location.
    places = d.get("PositionLocation") or [{}]
    location = places[0].get("LocationName") or d.get("PositionLocationDisplay") or ""
    text = [det.get("JobSummary"), *(det.get("MajorDuties") or []), det.get("Requirements")]
    pay = (d.get("PositionRemuneration") or [{}])[0]
    interval = _INTERVALS.get(pay.get("RateIntervalCode") or "")
    low, high = _salary(pay.get("MinimumRange")), _salary(pay.get("MaximumRange"))
    mode: Remote = (
        "remote"
        if det.get("RemoteIndicator")
        else "hybrid"
        if det.get("TeleworkEligible")
        else "onsite"
    )
    url = (d.get("PositionURI") or f"https://www.usajobs.gov/job/{job_id}").replace(":443/", "/")
    start = d.get("PositionStartDate")
    return JobStub(
        source="usajobs",
        url=url,
        title=" ".join(str(d["PositionTitle"]).split()),
        company=company,
        location=location,
        description="\n\n".join(t.strip() for t in text if t and t.strip()),
        posted_at=datetime.fromisoformat(start) if start else None,
        apply_url=url,
        remote=mode,
        salary_min=low if interval else None,
        salary_max=high if interval else None,
        salary_currency="USD" if interval and (low or high) else None,
        salary_interval=interval if low or high else None,
        ats="usajobs",
        extra={"id": str(job_id)},
    )


class USAJobs(Source):
    name = "usajobs"
    kind = "aggregator"
    parallel = 1

    def __init__(self, keys: KeyGetter | None = None) -> None:
        self._keys = keys

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        if get_keys(self._keys, self.name, FIELDS) is None:
            return []
        return [
            Task(
                self.name,
                f"usajobs:{query}:{location}",
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
        if code and code != "us":
            raise Unsupported("USAJobs lists US federal jobs only")
        keys = get_keys(self._keys, self.name, FIELDS)
        if keys is None:
            return
        headers = {"Authorization-Key": keys["api_key"], "User-Agent": keys["email"]}
        params: dict[str, Any] = {
            "Keyword": task.query,
            "ResultsPerPage": PAGE_SIZE,
            "DatePosted": min(task.posted_within_days, 60),  # the API accepts 0-60 days
        }
        if place:
            params["LocationName"] = place
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(URL, params={**params, "Page": page}, headers=headers)
            items = (data.get("SearchResult") or {}).get("SearchResultItems") or []
            if not items:
                return
            yield [s for i in items if (s := parse_job(i))]
            if len(items) < PAGE_SIZE or page * PAGE_SIZE >= task.limit:
                return
