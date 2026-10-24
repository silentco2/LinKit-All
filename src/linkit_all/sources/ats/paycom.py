"""Paycom career portals (paycomonline.net/v4/ats/web.php/portal/<client key>/jobs): the portal page
hands out the session token its own script uses, and the portal's API serves the postings. Logic
adapted from freehire (MIT)."""

import html
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from linkit_all.sources.ats._f12 import get_page, name_from_slug
from linkit_all.sources.ats._f16 import when
from linkit_all.sources.ats._f17 import hydrate
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.text import html_to_text

PORTAL = "https://www.paycomonline.net/v4/ats/web.php/portal"
PAGE = 50
MAX_PAGES = 200
CHUNK = 20  # posting details fetched together per page of stubs
_JWT = re.compile(r'"sessionJWT":"([^"]+)"')
_MANTLE = re.compile(r"portal-applicant-tracking\.[a-z0-9-]+\.paycomonline\.net")
_NO_BOARD = "Job board does not exist."
_FILTERS: dict[str, Any] = {
    "distanceFrom": 0,
    "workEnvironments": [],
    "positionTypes": [],
    "educationLevels": [],
    "categories": [],
    "travelTypes": [],
    "shiftTypes": [],
    "otherFilters": [],
    "keywordSearchText": "",
    "location": "",
    "sortOption": "",
}


class Paycom(Source):
    """The board is the client key: the hex string after /portal/ in the portal's URL."""

    name = "paycom"
    kind = "ats"
    url_patterns = (
        re.compile(r"paycomonline\.net/v4/ats/web\.php/portal/(\w+)", re.I),
        re.compile(r"paycomonline\.net/v4/ats/index\.php/jobs\?clientkey=(\w+)", re.I),
    )
    cdx_hosts = ("www.paycomonline.net/v4/ats/web.php/portal/*",)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.strip()
        if not re.fullmatch(r"\w+", board):
            raise ValueError(f"paycom: board {task.board!r} is not a client key")
        page = (await get_page(http, f"{PORTAL}/{board}/jobs/1")).text
        if _NO_BOARD in page:
            raise ValueError(f"paycom: board {board!r} does not exist")
        jwt, mantle = _JWT.search(page), _MANTLE.search(page)
        if not jwt or not mantle:
            raise ValueError(
                f"paycom: board {board!r}: no session token or API host in the portal page"
            )
        api, auth = f"https://{mantle[0]}/api/ats", {"Authorization": jwt[1], "Locale": "en-US"}
        company = name_from_slug(board)
        try:  # the employer's own name, when the portal gives one
            named = await http.get_json(f"{api}/company-name", headers=auth)
            company = str(named.get("companyName") or company)
        except (httpx.HTTPError, RetryableStatus, ValueError, AttributeError):
            pass

        async def build(ident: str) -> JobStub | None:
            return await self.posting(http, api, auth, board, company, ident)

        async for stubs in hydrate(await self.ids(http, api, auth), start_page, build, CHUNK):
            yield stubs

    @staticmethod
    async def ids(http: Http, api: str, auth: dict[str, str]) -> list[str]:
        """Posting ids from the previews search, a page at a time until the stated count."""
        found: dict[str, None] = {}
        for n in range(MAX_PAGES):
            body = {"skip": n * PAGE, "take": PAGE, "filtersForQuery": _FILTERS}
            data = await http.post_json(f"{api}/job-posting-previews/search", body, headers=auth)
            previews = data.get("jobPostingPreviews") or []
            if not previews:
                break
            found.update({str(p["jobId"]): None for p in previews if p.get("jobId")})
            if len(found) >= int(data.get("jobPostingPreviewsCount") or 0):
                break
        return list(found)

    @staticmethod
    async def posting(
        http: Http, api: str, auth: dict[str, str], board: str, company: str, ident: str
    ) -> JobStub | None:
        try:
            data = await http.get_json(f"{api}/job-postings/{ident}", headers=auth)
        except (httpx.HTTPError, RetryableStatus, ValueError):
            return None
        p = data.get("jobPosting") or {}
        if not p.get("jobId"):
            return None
        url = f"{PORTAL}/{board}/jobs/{p['jobId']}"
        location = p.get("location") or ""
        remote = (p.get("remoteType") or "").lower() == "remote"
        return JobStub(
            source="paycom",
            url=url,
            title=" ".join((p.get("jobTitle") or "").split()),
            company=company,
            location=location,
            description=html_to_text(html.unescape(p.get("description") or "")),
            posted_at=when(p.get("startDate")),
            ats="paycom",
            apply_url=url,
            remote="remote" if remote else remote_from_text(location),
            extra={"board": board, "id": str(p["jobId"])},
        )
