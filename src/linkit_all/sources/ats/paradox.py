"""Paradox ("Olivia"), the conversational-hiring platform behind many frontline employers' career
sites (<host>.paradox.ai/co/<site>/): a paged public search resource and a per-posting widget
resource. Logic adapted from freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

import httpx

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import XHR, paged
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import name_from_slug, when
from linkit_all.sources.text import html_to_text

PAGE = 100
_HOST = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.paradox\.ai$")
_SITE = re.compile(r"^[a-z0-9_.-]+$")


def _posted(script: str | None) -> datetime | None:
    """datePosted of the detail's JSON-LD script; the platform writes it as yy-mm-dd."""
    found = job_postings(script or "")
    raw = str((found[0] if found else {}).get("datePosted") or "").strip()
    if re.fullmatch(r"\d\d-\d\d-\d\d", raw):
        return when("20" + raw)
    return when(raw)


class Paradox(Source):
    """The board is `<host>/<site>`: `olivia.paradox.ai/AcmeCo` for olivia.paradox.ai/co/AcmeCo/."""

    name = "paradox"
    kind = "ats"
    url_patterns = (re.compile(r"((?:[\w-]+\.)+paradox\.ai)/co/([\w.-]+)", re.I),)
    cdx_hosts = ("*.paradox.ai/co/*",)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host, _, site = task.board.strip().lower().partition("/")
        if not _HOST.match(host) or not _SITE.match(site):
            raise ValueError(f"paradox: board {task.board!r} must be '<host>.paradox.ai/<site>'")
        base = f"https://{host}/api"

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            url = (
                f"{base}/job-list-site-ui/search-job?compsite_slug={quote(site)}"
                f"&limit={PAGE}&page={offset // PAGE + 1}"
            )
            data = await http.get_json(url, headers=XHR)
            if not data.get("success"):
                raise ValueError(f"paradox: {host}/{site} listing answered success=false")
            return data.get("jobs") or [], data.get("total_jobs")

        async for rows in paged(fetch, PAGE, start_page):
            built = await asyncio.gather(*(self.posting(http, base, host, site, r) for r in rows))
            yield [s for s in built if s is not None]

    async def posting(
        self, http: Http, base: str, host: str, site: str, row: dict[str, Any]
    ) -> JobStub | None:
        url = str(row.get("original_apply_url") or "")
        parts = urlsplit(url)
        ident = (parse_qs(parts.query).get("job_id") or [""])[0]
        # A row must link a posting on this very site; anything else is not ours to follow.
        if (
            (parts.hostname or "").lower() != host
            or parts.path.lower() != f"/co/{site}/job"
            or not ident
        ):
            return None
        detail_url = (
            f"{base}/job-posting/get_widget_extra_settings?compsite_slug={quote(site)}"
            f"&job_id={quote(ident)}"
        )
        try:
            detail = await http.get_json(detail_url, headers=XHR)
        except (httpx.HTTPError, RetryableStatus, ValueError):
            return None  # refused or gone: the posting is left for the next run, not stored empty
        job = detail.get("job") or {}
        description = html_to_text(job.get("description") or "")
        title = " ".join((row.get("job_title") or job.get("name") or "").split())
        if not description or not title:
            return None
        location = "; ".join(
            dict.fromkeys(p.strip() for p in row.get("location_name") or [] if p.strip())
        )
        return JobStub(
            source="paradox",
            url=url,
            title=title,
            company=(detail.get("company") or {}).get("name") or name_from_slug(site),
            location=location,
            description=description,
            posted_at=_posted(detail.get("google_json_ld")),
            ats="paradox",
            apply_url=url,
            remote=remote_from_text(location),
            extra={"board": f"{host}/{site}", "id": ident},
        )
