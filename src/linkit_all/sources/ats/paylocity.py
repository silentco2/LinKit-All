"""Paylocity recruiting career sites (recruiting.paylocity.com/Recruiting/Jobs/All/<company guid>):
the listing page embeds the whole job list as `window.pageData`, and each details page renders the
description. Logic adapted from freehire (MIT)."""

import html
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Remote, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, hydrate, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import next_element, node_text, when
from linkit_all.sources.text import html_to_text

BASE = "https://recruiting.paylocity.com"
CHUNK = 20  # details pages fetched together per page of stubs
_JOBS = re.compile(r'"Jobs"\s*:\s*(?=\[)')
_HYBRID = 1  # IndeedRemoteType of a hybrid role


def listed_jobs(page: str) -> list[dict[str, Any]]:
    """The Jobs array of the listing page's `window.pageData` blob."""
    m = _JOBS.search(page)
    if not m:
        raise ValueError("paylocity: no Jobs array in the listing page")
    jobs, _ = json.JSONDecoder().raw_decode(page, m.end())
    return [j for j in jobs if isinstance(j, dict)]


def description_of(html_text: str) -> str:
    """The block after the "Description" section header; failing that the JobPosting's body."""
    tree = LexborHTMLParser(html_text)
    for header in tree.css("div.job-listing-header"):
        if node_text(header).lower() == "description":
            block = next_element(header)
            return html_to_text(block.html or "") if block is not None else ""
    found = job_postings(html_text)
    return html_to_text(html.unescape(str(found[0].get("description") or ""))) if found else ""


def work_mode(job: dict[str, Any]) -> Remote | None:
    if not job.get("IsRemote"):
        return None
    return "hybrid" if job.get("IndeedRemoteType") == _HYBRID else "remote"


class Paylocity(Source):
    """The board is the company guid in the listing URL."""

    name = "paylocity"
    kind = "ats"
    url_patterns = (
        re.compile(r"recruiting\.paylocity\.com/recruiting/jobs/all/([0-9a-f-]{36})", re.I),
    )
    cdx_hosts = ("recruiting.paylocity.com/Recruiting/Jobs/All/*",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.strip()
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", board):
            raise ValueError(f"paylocity: board {task.board!r} is not a company guid")
        page = (await get_page(http, f"{BASE}/Recruiting/Jobs/All/{board}")).text

        async def build(job: dict[str, Any]) -> JobStub | None:
            return await self.posting(http, board, job)

        async for stubs in hydrate(listed_jobs(page), start_page, build, CHUNK):
            yield stubs

    @staticmethod
    async def posting(http: Http, board: str, job: dict[str, Any]) -> JobStub | None:
        ident = job.get("JobId")
        if not ident:
            return None
        url = f"{BASE}/Recruiting/Jobs/Details/{ident}"
        detail = await page_text(
            http, url
        )  # a page that cannot be read costs the body, not the job
        location = job.get("LocationName") or ""
        return JobStub(
            source="paylocity",
            url=url,
            title=" ".join((job.get("JobTitle") or "").split()),
            company=f"Paylocity {board}",  # the listing names no employer
            location=location,
            description=description_of(detail) if detail else "",
            posted_at=when(job.get("PublishedDate")),
            ats="paylocity",
            apply_url=url,
            remote=work_mode(job) or remote_from_text(location),
            extra={"board": board, "id": str(ident)},
        )
