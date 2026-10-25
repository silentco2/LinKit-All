"""EDJOIN (edjoin.org), the hiring board of California's K-12 school districts and colleges.
The listing (the site's own XHR) has no body; the posting page's JSON-LD does.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime
from math import ceil
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.tasks import feed_task

BASE = "https://www.edjoin.org"
LISTING = BASE + "/Home/LoadJobs"
PAGE = 500  # the endpoint answers 500 above 1000 rows
_DATE = re.compile(r"^/Date\((-?\d+)\)/$")  # .NET JSON date
_AMOUNT = re.compile(r"^\$?(\d[\d,]*(?:\.\d{1,2})?)$")  # a bare amount; pay boxes are free text
_PERIOD = {"Per Hour": "hour", "Daily": "day", "Monthly": "month", "Annually": "year"}


def _amount(text: str | None) -> float | None:
    m = _AMOUNT.match((text or "").strip())
    return float(m[1].replace(",", "")) if m else None


def _posted(value: str | None) -> datetime | None:
    m = _DATE.match(value or "")
    return from_epoch_ms(int(m[1])) if m and int(m[1]) > 0 else None  # .NET MinValue is negative


class Edjoin(Source):
    name = "edjoin"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        rows_per_page = min(PAGE, task.limit)
        listed: set[int] = set()  # ties on the sort date can repeat a posting on adjacent pages
        for page in range(start_page + 1, ceil(task.limit / rows_per_page) + 1):
            data = await http.get_json(LISTING, params=self.params(task, rows_per_page, page))
            rows = data.get("data") or []
            stubs = []
            for r in rows:
                if r.get("postingID") in listed:
                    continue
                listed.add(r.get("postingID"))
                if stub := self.stub(r):
                    stubs.append(stub)
            if stubs:
                yield stubs
            if not rows or page * rows_per_page >= data.get("totalRecords", 0):
                return

    @staticmethod
    def params(task: Task, rows: int, page: int) -> dict[str, Any]:
        # catID, districtID and recruitmentCenterID must be sent: the endpoint dereferences all
        # three and answers an HTML 500 page without them.
        return {
            "rows": rows, "page": page, "sort": "postingDate", "sortVal": 0, "order": "desc",
            "searchType": "all", "jobTypes": "", "days": task.posted_within_days,
            "catID": 0, "districtID": 0, "recruitmentCenterID": 0,
        }  # fmt: skip

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        if not p.get("postingID") or not (p.get("districtName") or "").strip():
            return None
        schedule = {s.strip() for s in (p.get("FullTimePartTime") or "").split(",")}
        place = (p.get("city") or "").strip() or (p.get("countyName") or "").strip()
        stub = JobStub(
            source=self.name,
            url=f"{BASE}/Home/JobPosting/{p['postingID']}",
            title=(p.get("positionTitle") or "").strip(),
            company=p["districtName"].strip(),
            location=", ".join(x for x in (place, (p.get("stateName") or "").strip()) if x),
            posted_at=_posted(p.get("postingDate")),
            remote="remote" if "Remote" in schedule else None,
            extra={"id": p["postingID"]},
        )
        return self.with_salary(stub, p)

    @staticmethod
    def with_salary(stub: JobStub, p: dict[str, Any]) -> JobStub:
        match (p.get("SalaryInfoSelect") or "").strip():
            case "Pay Range":
                low, high, period = (
                    p.get("PayRangeFrom"),
                    p.get("PayRangeTo"),
                    p.get("PayRangeDropdown"),
                )
            case "Single Rate":
                low = high = p.get("SingleRate")
                period = p.get("SingleRateDropdown")
            case _:
                return stub  # "Dependent": no figure published
        interval = _PERIOD.get((period or "").strip())
        lo, hi = _amount(low), _amount(high)
        if not interval or (lo is None and hi is None):
            return stub  # an amount with an unknown period would be published under a wrong one
        return stub.model_copy(
            update={"salary_min": lo, "salary_max": hi, "salary_currency": "USD",
                    "salary_interval": interval}
        )  # fmt: skip

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        resp = await http.get(stub.url)
        if resp.status_code in (404, 410):  # taken down
            return stub
        resp.raise_for_status()
        for posting in job_postings(resp.text):
            if text := strip_html(posting.get("description") or "", True):
                return stub.model_copy(update={"description": text})
        return stub
