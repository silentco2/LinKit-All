"""Rippling public ATS board API (ats.rippling.com/api/v1/board/{board}/jobs). Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://ats.rippling.com/api/v1/board/{board}/jobs"
JOB_URL = "https://ats.rippling.com/{board}/jobs/{id}"
_URL = re.compile(r"ats\.rippling\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)/jobs/([\w-]+)", re.I)


class Rippling(Source):
    name = "rippling"
    kind = "ats"
    url_patterns = (re.compile(r"ats\.rippling\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)", re.I),)
    cdx_hosts = ("ats.rippling.com/*",)
    parallel = 4

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        postings = await http.get_json(API.format(board=task.board))
        company = name_from_slug(task.board)
        yield [self.stub(p, task.board, company) for p in postings if p.get("uuid")]

    @staticmethod
    def stub(p: dict[str, Any], board: str, company: str) -> JobStub:
        where = (p.get("workLocation") or {}).get("label") or ""
        url = p.get("url") or JOB_URL.format(board=board, id=p["uuid"])
        return JobStub(
            source="rippling",
            url=url,
            title=(p.get("name") or "").strip(),
            company=company,
            location=where,
            ats="rippling",
            apply_url=url,
            remote=remote_from_text(where),
            extra={"board": board, "id": p["uuid"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _URL.search(stub.url)
        if not m:
            return stub
        board, uuid = m.groups()
        resp = await http.get(f"{API.format(board=board)}/{uuid}")
        if resp.status_code in (404, 410):
            return stub
        resp.raise_for_status()
        d = resp.json()
        # description.company is boilerplate about the employer, not the role.
        role = (d.get("description") or {}).get("role") or ""
        return stub.model_copy(
            update={
                "description": html_to_text(role),
                "posted_at": from_iso(d.get("createdOn")) or stub.posted_at,
            }
        )
