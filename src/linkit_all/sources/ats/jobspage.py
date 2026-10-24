"""Jobspage (jobspage.co), a careers-page builder for small companies: the tenant page embeds its
postings in __NEXT_DATA__, each posting's own page holds the HTML body as a schema.org JobPosting.
Logic adapted from freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from linkit_all.sources.ats._f13 import get_page, name_from_slug
from linkit_all.sources.ats._f16 import GONE, chunks, next_data, when
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

_ID = re.compile(r"^https://([\w-]+)\.jobspage\.co/([\w-]+)")
_REMOTE: dict[str, Remote] = {"remote only": "remote", "no remote": "onsite"}
# "Remote friendly" says remote work is possible, not what the posting is: left unset.


async def _body(http: Http, url: str) -> dict[str, Any] | None:
    """The posting page's JobPosting block; {} when it can't be read right now, None when the
    platform says it is gone (it answers "no such page" with a redirect loop to /404)."""
    try:
        resp = await get_page(http, url)
    except httpx.TooManyRedirects:
        return None
    except GONE:
        return {}
    found = job_postings(resp.text)[:1]
    return found[0] if found else {}


class JobsPage(Source):
    """The board is the tenant subdomain: `<board>.jobspage.co`."""

    name = "jobspage"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([\w-]+)\.jobspage\.co", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        base = f"https://{task.board}.jobspage.co"
        try:
            resp = await get_page(http, base)
        except httpx.TooManyRedirects as exc:
            raise ValueError(f"jobspage: no career site for {task.board!r}") from exc
        props = ((next_data(resp.text) or {}).get("props") or {}).get("pageProps") or {}
        postings = props.get("jobsData")
        if not isinstance(postings, list):  # a reshaped page must not read as "no openings"
            raise ValueError(f"jobspage: no jobsData in the page of {task.board!r}")
        company = str((props.get("companyData") or {}).get("companyName") or "").strip()
        company = company or name_from_slug(task.board)
        live = [p for p in postings if p.get("id") and p.get("jobTitle") and not p.get("isExpired")]
        for chunk in chunks(live, start_page):
            urls = [f"{base}/{p['id']}" for p in chunk]
            bodies = await asyncio.gather(*(_body(http, u) for u in urls))
            yield [
                self.stub(p, u, b, task.board, company)
                for p, u, b in zip(chunk, urls, bodies, strict=True)
                if b is not None
            ]

    @staticmethod
    def stub(
        p: dict[str, Any], url: str, body: dict[str, Any], board: str, company: str
    ) -> JobStub:
        location = ", ".join(
            x for x in (str(p.get(k) or "").strip() for k in ("city", "country")) if x
        )
        return JobStub(
            source="jobspage",
            url=url,
            title=" ".join(p["jobTitle"].split()),
            company=company,
            location=location,
            description=strip_html(body.get("description") or ""),
            posted_at=when(body.get("datePosted")),
            ats="jobspage",
            apply_url=url,
            remote=_REMOTE.get(str(p.get("remoteJob") or "").strip().lower()),
            extra={"board": board, "id": p["id"], "employment": p.get("employmentType")},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        body = await _body(http, stub.url) if _ID.match(stub.url) else None
        if not body or not body.get("description"):
            return stub
        return stub.model_copy(
            update={
                "description": strip_html(body["description"]),
                "posted_at": stub.posted_at or when(body.get("datePosted")),
            }
        )
