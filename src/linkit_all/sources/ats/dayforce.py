"""Dayforce (Ceridian) career sites, all served from jobs.dayforcehcm.com/<culture>/<tenant>/<site>.
Logic adapted from freehire (MIT)."""

import html
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug

BASE = "https://jobs.dayforcehcm.com"
PAGE_SIZE = 25  # fixed by the platform: the request only carries an offset
DEFAULT_CULTURE = "en-US"
_JOB_URL = re.compile(r"dayforcehcm\.com/[\w-]+/[\w-]+/[\w-]+/jobs/(\d+)", re.I)


class Dayforce(Source):
    """The board is `<tenant>/<site>`, as in `jobs.dayforcehcm.com/en-US/<tenant>/<site>`; a third
    segment names the culture (`gm/candidateportal/fr-CA`) for sites that do not answer en-US.

    The listing is a POST guarded by the site's own double-submit CSRF pair: `/api/auth/csrf`
    sets a cookie (kept by the HTTP client) and returns the token that goes back in a header."""

    name = "dayforce"
    kind = "ats"
    url_patterns = (
        re.compile(r"jobs\.dayforcehcm\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?([\w-]+)/([\w-]+)", re.I),
    )
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        parts = task.board.split("/")
        if not 2 <= len(parts) <= 3 or not parts[0] or not parts[1]:
            raise ValueError(f"dayforce board {task.board!r} must be 'tenant/site[/culture]'")
        tenant, site = parts[0], parts[1]
        culture = parts[2] if len(parts) == 3 and parts[2] else DEFAULT_CULTURE
        token = await self._csrf(http)

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            nonlocal token
            body = {
                "clientNamespace": tenant,
                "jobBoardCode": site,
                "cultureCode": culture,
                "paginationStart": offset,
            }
            url = f"{BASE}/api/geo/{tenant}/jobposting/search"
            try:
                data = await http.post_json(url, body, headers={"X-CSRF-TOKEN": token})
            except httpx.HTTPStatusError as e:
                if e.response.status_code != 403:
                    raise
                token = await self._csrf(
                    http
                )  # a stale token looks like a 403: mint one, retry once
                data = await http.post_json(url, body, headers={"X-CSRF-TOKEN": token})
            return data.get("jobPostings") or [], data.get("maxCount")

        async for items in paged(fetch, PAGE_SIZE, start_page):
            yield [self.stub(p, tenant, site, culture, task.board) for p in items]

    @staticmethod
    async def _csrf(http: Http) -> str:
        token = (await http.get_json(f"{BASE}/api/auth/csrf")).get("csrfToken")
        if not token:
            raise ValueError("dayforce: the CSRF bootstrap issued no token")
        return str(token)

    @staticmethod
    def stub(p: dict[str, Any], tenant: str, site: str, culture: str, board: str) -> JobStub:
        places = []
        for a in p.get("postingLocations") or []:
            place = ", ".join(
                x for x in (a.get("cityName"), a.get("stateCode"), a.get("isoCountryCode")) if x
            )
            if place and place not in places:
                places.append(place)
        location = "; ".join(places)
        url = f"{BASE}/{culture}/{tenant}/{site}/jobs/{p['jobPostingId']}"
        title = (p.get("jobTitle") or "").strip()
        return JobStub(
            source="dayforce",
            url=url,
            title=title,
            company=name_from_slug(tenant),
            location=location,
            description=html.unescape(
                p.get("jobDescription") or ""
            ).strip(),  # tags stripped, entities not
            posted_at=from_iso(p.get("postingStartTimestampUTC")),
            ats="dayforce",
            apply_url=url,
            remote="remote" if p.get("hasVirtualLocation") else remote_from_text(location, title),
            extra={"board": board, "id": p["jobPostingId"]},
        )
