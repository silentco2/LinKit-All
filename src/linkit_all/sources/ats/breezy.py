"""Breezy HR career boards ({board}.breezy.hr): a JSON listing plus the position page's
schema.org JobPosting for the description. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.text import html_to_text

LIST = "https://{board}.breezy.hr/json"
_URL = re.compile(r"//([\w-]+)\.breezy\.hr/p/", re.I)


class Breezy(Source):
    name = "breezy"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.breezy\.hr", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        data = await http.get_json(LIST.format(board=task.board.lower()))
        yield [self.stub(p, task.board) for p in data if p.get("id") and p.get("url")]

    @staticmethod
    def stub(p: dict[str, Any], board: str) -> JobStub:
        loc = p.get("location") or {}
        city, country = loc.get("city"), (loc.get("country") or {}).get("name")
        location = ", ".join(x for x in (city, country) if x)
        company = (p.get("company") or {}).get("name") or board.replace("-", " ").title()
        return JobStub(
            source="breezy",
            url=p["url"],
            title=(p.get("name") or "").strip(),
            company=company,
            location=location,
            posted_at=from_iso(p.get("published_date")),
            ats="breezy",
            apply_url=p["url"],
            # is_remote is the authoritative flag; the location text is only a fallback.
            remote="remote" if loc.get("is_remote") else remote_from_text(location),
            extra={
                "board": board,
                "id": str(p["id"]),
                "employment": (p.get("type") or {}).get("name"),
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not _URL.search(stub.url):
            return stub
        await http.allowed(stub.url)
        resp = await http.get(stub.url)
        if resp.status_code in (404, 410):
            return stub
        resp.raise_for_status()
        found = job_postings(resp.text)[:1]
        text = html_to_text(found[0].get("description") or "", escaped=True) if found else ""
        return stub.model_copy(update={"description": text}) if text else stub
