"""SchoolSpring (schoolspring.com), the K-12 education job board PowerSchool runs. The keyless
search API lists postings by keyword; the body comes from each posting's own endpoint
(`fetch_details`). Logic adapted from freehire (MIT)."""

import html
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import query_tasks
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

API = "https://api.schoolspring.com"
DOMAIN = "www.schoolspring.com"
JOB_URL = f"https://{DOMAIN}/jobdetail?jobId={{}}"
PAGE = 100
MAX_PAGES = 50
_ID = re.compile(r"[?&]jobId=(\d+)")


def _text(value: str | None) -> str:
    return html.unescape(value or "").strip()  # the listing leaves entities in titles


class SchoolSpring(Source):
    name = "schoolspring"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        count = 0
        listed: set[int] = set()
        for page in range(start_page + 1, MAX_PAGES + 1):
            params = {"domainName": DOMAIN, "keyword": task.query, "page": page, "size": PAGE,
                      "sortDateAscending": "false"}  # fmt: skip
            data = await http.get_json(f"{API}/api/Jobs/GetPagedJobsWithSearch", params=params)
            if not data.get("success"):
                raise RuntimeError(f"schoolspring search failed: {data.get('message')}")
            rows = [r for r in (data.get("value") or {}).get("jobsList") or []
                    if r.get("jobId") and r["jobId"] not in listed]  # fmt: skip
            listed.update(r["jobId"] for r in rows)
            stubs = [s for r in rows[: task.limit - count] if (s := self.stub(r))]
            count += len(rows[: task.limit - count])
            if stubs:
                yield stubs
            if not rows or count >= task.limit:
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        company, title = _text(r.get("employer")), _text(r.get("title"))
        if not company or not title:
            return None
        location = _text(r.get("location"))
        url = JOB_URL.format(r["jobId"])
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=location,
            posted_at=from_iso(r.get("displayDate")),
            ats=self.name,
            apply_url=url,
            remote=remote_from_text(title, location),
            extra={"id": r["jobId"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        if not m:
            return stub
        resp = await http.get_json(f"{API}/api/Jobs/{m[1]}", params={"domainName": DOMAIN})
        info = (resp.get("value") or {}).get("jobInfo") if resp.get("success") else None
        if not info or not (info.get("jobDescription") or "").strip():
            return stub
        places = [_text(p.get("displayLocation")) for p in resp["value"].get("jobLocations") or []]
        places = list(dict.fromkeys(p for p in places if p))
        return stub.model_copy(update={
            "description": strip_html(info["jobDescription"]),
            "location": "; ".join(places) or stub.location,
        })  # fmt: skip
