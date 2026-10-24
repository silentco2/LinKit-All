"""Phenom career sites (a Phenom-hosted careers page on the employer's own host): the page's own
/widgets endpoint answers `refineSearch` (the list) and `jobDetail` (one posting) as JSON. Logic
adapted from freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx

from linkit_all.sources.ats._f12 import name_from_host
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.text import html_to_text

PAGE = 100


def posted(value: str | None) -> datetime | None:
    """ "2026-05-17T22:00:00.000+0000" as naive UTC; None when it is missing or odd."""
    try:
        return (
            datetime.strptime(value or "", "%Y-%m-%dT%H:%M:%S.%f%z")
            .astimezone(UTC)
            .replace(tzinfo=None)
        )
    except ValueError:
        return None


def job_url(host: str, locale: str | None, seq: str) -> str:
    """The posting's page: /<country>/<lang>/job/<seq> for a locale such as en_GLOBAL, else
    /job/<seq>."""
    lang, _, country = (locale or "").partition("_")
    if lang and country:
        return f"https://{host}/{country.lower()}/{lang.lower()}/job/{seq}"
    return f"https://{host}/job/{seq}"


class Phenom(Source):
    """The board is the careers host (`careers.acme.com`). Phenom sites sit on the employer's own
    domain, so there is no URL pattern: list one as `phenom:careers.acme.com`."""

    name = "phenom"
    kind = "ats"
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board.strip().lower()
        if "." not in host or re.search(r"[/:?#@\s]", host):
            raise ValueError(f"phenom: board {task.board!r} is not a careers host")
        url, company = f"https://{host}/widgets", name_from_host(host)

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            body = {
                "deviceType": "desktop",
                "ddoKey": "refineSearch",
                "jobs": True,
                "from": offset,
                "size": PAGE,
            }
            data = await http.post_json(url, body)
            return (((data.get("refineSearch") or {}).get("data") or {}).get("jobs")) or [], None

        async for rows in paged(fetch, PAGE, start_page):
            built = await asyncio.gather(*(self.posting(http, url, host, company, r) for r in rows))
            yield [s for s in built if s is not None]

    @staticmethod
    async def posting(
        http: Http, url: str, host: str, company: str, row: dict[str, Any]
    ) -> JobStub | None:
        seq = str(row.get("jobSeqNo") or "")
        if not seq:
            return None
        body = {
            "deviceType": "desktop",
            "ddoKey": "jobDetail",
            "pageName": "job-details",
            "jobSeqNo": seq,
        }
        try:
            data = await http.post_json(url, body)
        except (httpx.HTTPError, RetryableStatus, ValueError):
            return None
        job = ((data.get("jobDetail") or {}).get("data") or {}).get("job") or {}
        if not job.get("description"):
            return None
        title = " ".join((row.get("title") or job.get("title") or "").split())
        location = row.get("cityState") or ""
        link = job_url(host, row.get("locale"), seq)
        return JobStub(
            source="phenom",
            url=link,
            title=title,
            company=company,
            location=location,
            description=html_to_text(job["description"]),
            posted_at=posted(row.get("postedDate")),
            ats="phenom",
            apply_url=link,
            remote=remote_from_text(location),
            extra={"board": host, "id": seq},
        )
