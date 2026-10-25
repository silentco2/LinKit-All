"""Tencent's own careers site (careers.tencent.com), the mainland-China catalogue limited to the
site's Technology category. The listing carries only the responsibilities, so the full text comes
from the posting API. Postings re-listed from Tencent's Workday tenant are skipped (the workday
plugin reads those). A single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

import re
import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import paged
from linkit_all.sources.companies._f41 import limited, query_tasks
from linkit_all.sources.http import Http

API = "https://careers.tencent.com/tencentcareer/api/post"
JOB = "https://careers.tencent.com/jobdesc.html?postId="
TECH = "40001"  # the site's top-level Technology category
PAGE = 100
NATIVE = 1  # SourceID of a posting authored on this site; 4 is a re-listed Workday posting
_ID = re.compile(r"postId=(\d+)")


def posted(value: str | None) -> datetime | None:
    """The en-us LastUpdateTime ("October 15,2026"), the only date the site states."""
    try:
        return datetime.strptime((value or "").strip(), "%B %d,%Y")
    except ValueError:
        return None


def parse_post(p: dict[str, Any]) -> JobStub | None:
    pid = str(p.get("PostId") or "")
    if not (pid.isdigit() and p.get("RecruitPostName")) or p.get("SourceID") != NATIVE:
        return None
    place = [str(p.get(k) or "").strip() for k in ("LocationName", "CountryName")]
    return JobStub(
        source="tencent",
        ats="tencent",
        url=JOB + pid,
        title=" ".join(str(p["RecruitPostName"]).split()),
        company="Tencent",
        location=", ".join(dict.fromkeys(x for x in place if x)),
        posted_at=posted(p.get("LastUpdateTime")),
        apply_url=JOB + pid,
        extra={"id": pid},
    )


class Tencent(Source):
    name = "tencent"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            params = {
                "timestamp": int(time.time() * 1000),
                "parentCategoryId": TECH,
                "pageIndex": offset // PAGE + 1,
                "pageSize": PAGE,
                "language": "en-us",  # names the country and city in English
                "keyword": task.query,
            }
            data = (await http.get_json(f"{API}/Query", params=params)).get("Data") or {}
            return data.get("Posts") or [], data.get("Count")

        async def stubs() -> AsyncIterator[list[JobStub]]:
            async for posts in paged(fetch, PAGE, start_page):
                yield [s for p in posts if (s := parse_post(p))]

        async for page in limited(stubs(), task.limit):
            yield page

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        if not m:
            return stub
        params = {"timestamp": int(time.time() * 1000), "postId": m[1], "language": "en-us"}
        d = (await http.get_json(f"{API}/ByPostId", params=params)).get("Data") or {}
        if d.get("PostId") != m[1]:
            return stub
        text = "\n\n".join(
            str(d.get(k) or "").replace("\r", "").strip()
            for k in ("Introduction", "Responsibility", "Requirement")
        ).strip()
        return stub.model_copy(update={"description": text}) if text else stub
