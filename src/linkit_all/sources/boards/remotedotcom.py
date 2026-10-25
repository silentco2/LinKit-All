"""remote.com's public jobs board, a curated remote-jobs listing (about 5,700 postings). The site is
a Next.js app; asking for the `RSC` flight (what its own pages request) returns the listing as
plain JSON and a posting page as its schema.org JobPosting, with no HTML to scrape. The listing has
no body, so the description comes from `fetch_details`. Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.ats._f16 import when
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

LIST = "https://remote.com/jobs/all?page={}"
JOB = "https://remote.com/jobs/{}/{}"
MAX_PAGES = 2000
RSC = {"RSC": "1"}  # answer with the data stream instead of the rendered page
_ROW = re.compile(rb"[^0-9a-f]([0-9a-f]+):T([0-9a-f]+),")  # a text row: id:T<hex byte length>,
_MODES: dict[str, Remote] = {"remote": "remote", "hybrid": "hybrid", "on_site": "onsite"}
_PERIODS = {"yearly": "year", "monthly": "month", "daily": "day", "hourly": "hour"}


def listing(flight: str) -> dict[str, Any]:
    """The `jobsData` object of a listing flight ({} when absent). The decoder finds where the
    object ends, so braces inside a title cannot confuse it."""
    at = flight.find('"jobsData":')
    if at < 0:
        return {}
    try:
        data, _ = json.JSONDecoder().raw_decode(flight, at + len('"jobsData":'))
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def description(flight: str) -> str:
    """The body of the JobPosting a posting flight carries in one of its text rows."""
    raw = flight.encode()
    for m in _ROW.finditer(raw):
        row = raw[m.end() : m.end() + int(m[2], 16)].decode("utf-8", "replace")
        try:
            doc = json.loads(row, strict=False)
        except ValueError:
            continue
        for node in doc if isinstance(doc, list) else [doc]:
            if isinstance(node, dict) and node.get("@type") == "JobPosting":
                return str(node.get("description") or "")
    return ""


def _place(p: dict[str, Any]) -> str:
    work = p.get("workplaceLocation") or {}
    if work.get("type") not in (None, "", "remote"):
        where = ", ".join(
            x for x in (work.get("city"), (work.get("country") or {}).get("name")) if x
        )
        if where:
            return where
    hire = p.get("hiringLocation") or {}
    kind = hire.get("type")
    if kind == "global":
        return "Worldwide"
    if kind == "location":
        names = [(i.get("value") or {}).get("name") for i in hire.get("includedLocations") or []]
        return ", ".join(dict.fromkeys(n for n in names if n))
    zone = (hire.get("timezone") or {}).get("name")
    return f"{zone} timezone" if kind == "timezone" and zone else ""


def stub(p: dict[str, Any]) -> JobStub | None:
    company = p.get("companyProfile") or {}
    if p.get("status") != "published" or not p.get("slug") or not company.get("name"):
        return None
    pay = p.get("compensation") or {}
    interval = _PERIODS.get(pay.get("frequency") or "")
    currency = (pay.get("currency") or {}).get("code")
    lo, hi = (pay.get("minimum") or 0) / 100, (pay.get("maximum") or 0) / 100  # minor units
    priced = bool(interval and currency and (lo or hi))
    url = JOB.format(company.get("slug"), p["slug"])
    return JobStub(
        source="remotedotcom",
        url=url,
        title=(p.get("title") or "").strip(),
        company=company["name"],
        location=_place(p),
        posted_at=when(p.get("publishedAt")),
        ats="remotedotcom",
        apply_url=url,
        remote=_MODES.get((p.get("workplaceLocation") or {}).get("type") or ""),
        salary_min=lo or None if priced else None,
        salary_max=hi or None if priced else None,
        salary_currency=currency if priced else None,
        salary_interval=interval if priced else None,
        extra={"id": p["slug"], "employment": p.get("employmentType")},
    )


class RemoteDotCom(Source):
    name = "remotedotcom"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        count = 0
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = LIST.format(page)
            await http.allowed(url)
            resp = await http.get(url, headers=RSC)
            resp.raise_for_status()
            data = listing(resp.text)
            rows = data.get("jobs") or []
            stubs = [s for p in rows if (s := stub(p))][: task.limit - count]
            count += len(stubs)
            yield stubs  # an empty page still counts, so a resume lines up
            if not rows or count >= task.limit or page >= (data.get("totalPages") or 0):
                return

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        await http.allowed(stub.url)
        resp = await http.get(stub.url, headers=RSC)
        resp.raise_for_status()
        text = strip_html(description(resp.text))
        return stub.model_copy(update={"description": text}) if text else stub
