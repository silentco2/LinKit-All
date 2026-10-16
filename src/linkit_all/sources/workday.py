"""Workday career sites via the public "cxs" JSON endpoint behind every myworkdayjobs.com page.

Board slug is "tenant/wdN/site", e.g. "nvidia/wd5/NVIDIAExternalCareerSite".
"""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

HOST = "https://{tenant}.{wd}.myworkdayjobs.com"
PAGE = 20  # the largest page size Workday's list endpoint accepts
# The enrich stage only hands us the stored URL, so ids are recovered from it.
_URL = re.compile(
    r"https://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)(/job/\S+)"
)
_AGO = re.compile(r"(\d+)\+?\s+days?\s+ago", re.I)


def parse_posted(text: str | None, now: datetime | None = None) -> datetime | None:
    """ "Posted 3 Days Ago" -> naive UTC midnight of that day; None when unrecognised."""
    if not text:
        return None
    low = text.lower()
    days = 0 if "today" in low else 1 if "yesterday" in low else None
    if days is None and (m := _AGO.search(low)):
        days = int(m.group(1))  # "30+ days ago" -> 30, the best we know
    if days is None:
        return None
    today = (now or datetime.now(UTC)).replace(
        tzinfo=None, hour=0, minute=0, second=0, microsecond=0
    )
    return today - timedelta(days=days)


class Workday(Source):
    name = "workday"

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        tenant, wd, site = task.board.split("/")
        url = f"{HOST.format(tenant=tenant, wd=wd)}/wday/cxs/{tenant}/{site}/jobs"
        company = tenant.replace("-", " ").title()
        offset = start_page * PAGE
        total = 0  # only the first page reports it (later pages say 0), so a resume cannot know
        while True:
            body = {"appliedFacets": {}, "limit": PAGE, "offset": offset, "searchText": ""}
            data = await http.post_json(url, body)
            postings = data.get("jobPostings") or []
            if not postings:
                return
            total = total or data.get("total") or 0
            yield [self.stub(p, task.board, company) for p in postings]
            offset += len(postings)
            if len(postings) < PAGE or (total and offset >= total):
                return

    @staticmethod
    def stub(p: dict[str, Any], board: str, company: str) -> JobStub:
        tenant, wd, site = board.split("/")
        url = f"{HOST.format(tenant=tenant, wd=wd)}/{site}{p['externalPath']}"
        return JobStub(
            source="workday",
            url=url,
            title=p["title"],
            company=company,
            location=p.get("locationsText") or "",
            posted_at=parse_posted(p.get("postedOn")),
            ats="workday",
            apply_url=url,
            remote=remote_from_text(p.get("locationsText"), p["title"]),
            extra={
                "board": board,
                "external_path": p["externalPath"],
                "req_id": (p.get("bulletFields") or [""])[0],
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        tenant, wd, site, path = m.groups()
        j = await http.get_json(
            f"{HOST.format(tenant=tenant, wd=wd)}/wday/cxs/{tenant}/{site}{path}"
        )
        info = j.get("jobPostingInfo") or {}
        return stub.model_copy(
            update={
                "description": html_to_text(info.get("jobDescription") or ""),
                "apply_url": info.get("externalUrl") or stub.apply_url,
            }
        )
