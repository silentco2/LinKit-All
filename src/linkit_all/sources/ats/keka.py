"""Keka career portals ({board}.keka.com/careers): the portal's own listing API returns every open
posting with its description. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

FULL_TIME = 2  # the portal's own script shows jobType 2 as "Full Time" and any other as part time


class Keka(Source):
    """The board is the Keka subdomain: `<board>.keka.com/careers`."""

    name = "keka"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([\w-]+)\.keka\.com", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one response holds the whole board
            return
        base = f"https://{task.board}.keka.com/careers"
        company = name_from_slug(task.board)
        try:  # the organisation's own name: nice to have, never a reason to stop
            info = await http.get_json(f"{base}/api/organization/default/careerportalinfo")
            company = (info.get("name") or "").strip() or company
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        postings = await http.get_json(f"{base}/api/jobs/default/active")
        if not isinstance(postings, list):
            raise ValueError(f"keka: unexpected answer for {task.board!r}")
        yield [self.stub(p, base, company, task.board) for p in postings if p.get("id")]

    @staticmethod
    def stub(p: dict[str, Any], base: str, company: str, board: str) -> JobStub:
        place = (p.get("jobLocations") or [{}])[0]
        location = ", ".join(
            x for x in (place.get("city"), place.get("state"), place.get("countryName")) if x
        )
        url = f"{base}/jobdetails/{p['id']}"
        title = " ".join(str(p.get("title") or "").split())
        return JobStub(
            source="keka",
            url=url,
            title=title,
            company=company,
            location=location,
            description=strip_html(p.get("description") or ""),
            posted_at=from_iso(p.get("publishedOn")),
            ats="keka",
            apply_url=url,
            remote=remote_from_text(location, title),  # no structured remote flag
            extra={
                "board": board,
                "id": str(p["id"]),
                "employment": "full_time" if p.get("jobType") == FULL_TIME else "part_time",
            },
        )
