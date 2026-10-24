"""HumanBit (jobs.humanbit.ai/<board>), a multi-tenant ATS built on Next.js: the listing page
inlines every posting's id and employer name, each posting page the structured fields. Logic
adapted from freehire (MIT)."""

import contextlib
import json
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from linkit_all.sources.ats._f13 import get_page, name_from_slug
from linkit_all.sources.ats.deel import bracket_slice, decode_flight, text_rows
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.text import html_to_text

BOARD = "https://jobs.humanbit.ai/{board}"
JOB = "https://jobs.humanbit.ai/{board}/jobs/{id}"


def _description(value: Any, rows: dict[str, str]) -> str:
    """A description is inline HTML or a "$<id>" reference to a text row of the same page."""
    text = str(value or "")
    return html_to_text(rows.get(text[1:], "") if text.startswith("$") else text)


class HumanBit(Source):
    """The board is the tenant's path segment."""

    name = "humanbit"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.humanbit\.ai/([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one page holds every posting
            return
        board = task.board
        flight = decode_flight((await get_page(http, BOARD.format(board=board))).text)
        raw = bracket_slice(flight, '"jobs":', "[", "]")
        if raw is None:
            raise ValueError(f"humanbit: no postings in the {board} page (markup changed?)")
        rows = text_rows(flight)
        stubs = []
        for item in (j for j in json.loads(raw) if j.get("id")):
            url = JOB.format(board=board, id=item["id"])
            stub = JobStub(
                source=self.name,
                url=url,
                title=(item.get("title") or "").strip(),
                company=item.get("org_name") or name_from_slug(board),
                location=(item.get("location") or "").strip(),
                description=_description(item.get("description"), rows),
                posted_at=from_iso(item.get("created_at")),
                ats=self.name,
                apply_url=url,
                remote=remote_from_text(item.get("title"), item.get("location")),
                extra={"board": board, "id": item["id"]},
            )
            hydrated: JobStub | None = stub  # the detail page only adds the structured fields
            with contextlib.suppress(httpx.HTTPError, RetryableStatus):
                hydrated = await self.hydrate(http, stub)
            if hydrated:
                stubs.append(hydrated)
        yield stubs

    async def hydrate(self, http: Http, stub: JobStub) -> JobStub | None:
        """Add the remote flag, employment type and the detail page's own description. None =
        the page answers but holds no job (a removed posting renders a client-side "not found")."""
        try:
            flight = decode_flight((await get_page(http, stub.url)).text)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 410):
                return None
            raise
        raw = bracket_slice(flight, '"job":{"id"', "{", "}")
        job: dict[str, Any] = json.loads(raw) if raw else {}
        if not job:
            return None
        desc = _description(job.get("description"), text_rows(flight))
        return stub.model_copy(
            update={
                "title": (job.get("title") or stub.title).strip(),
                "location": (job.get("location") or stub.location).strip(),
                "description": desc or stub.description,
                "remote": "remote" if job.get("remote") else stub.remote,
                "extra": {**stub.extra, "employment": job.get("employment_type")},
            }
        )
