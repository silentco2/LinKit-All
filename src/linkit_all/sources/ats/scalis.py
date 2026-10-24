"""Scalis (<board>.scalis.ai), a multi-tenant ATS on Next.js: each listing page inlines full job
objects in its RSC flight. Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.ats._f13 import get_page, mode, name_from_slug
from linkit_all.sources.ats.deel import bracket_slice, decode_flight, text_rows
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

LIST = "https://{board}.scalis.ai/jobs?page={page}&limit=10&sortBy=SORT_BEST_MATCH"
JOB_URL = "https://{board}.scalis.ai/job/{id}"
MAX_PAGES = 500
_PERIOD = {"SALARY": "year", "HOURLY": "hour"}  # the payment enum states the salary unit


def description(p: dict[str, Any], rows: dict[str, str]) -> tuple[str, bool]:
    """(body, had_reference). description/descriptionHtml are "$<id>" references into the flight's
    text rows (or, rarely, inline); the HTML form is preferred, plain text is the fallback."""
    had_ref = False
    for field in (p.get("descriptionHtml") or "", p.get("description") or ""):
        if not field.startswith("$"):
            if field:
                return field, had_ref
            continue
        had_ref = True
        if rows.get(field[1:]):
            return rows[field[1:]], True
    return "", had_ref


class Scalis(Source):
    """The board is the tenant subdomain. Pages hold 10 postings (the server clamps `limit`); an
    empty page ends the board."""

    name = "scalis"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w-])(?!www\.|app\.)([\w-]+)\.scalis\.ai", re.I),)
    cdx_hosts = ("*.scalis.ai",)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        company = name_from_slug(task.board)
        refs = resolved = 0
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = LIST.format(board=task.board, page=page)
            flight = decode_flight((await get_page(http, url)).text)
            raw = bracket_slice(flight, '"initialData":{"results"', "{", "}")
            if raw is None:
                raise ValueError(f"scalis: {task.board} page {page}: no initialData object")
            results = [p for p in json.loads(raw).get("results") or [] if p.get("id")]
            if not results:
                # Every description reference failing means the row format changed.
                if refs and not resolved:
                    raise ValueError(
                        f"scalis: {refs} description references on {task.board}, none resolved"
                    )
                return
            rows = text_rows(flight)
            stubs = []
            for p in results:
                body, had_ref = description(p, rows)
                refs += had_ref
                resolved += bool(had_ref and body)
                stubs.append(self.stub(p, body, task.board, company))
            yield stubs
        raise ValueError(f"scalis: {task.board}: no end to the board after {MAX_PAGES} pages")

    @staticmethod
    def stub(p: dict[str, Any], body: str, board: str, company: str) -> JobStub:
        # Not p["company"]: the flight replaces repeats with back-reference strings, and a board
        # is a single company anyway.
        where = "; ".join(
            dict.fromkeys(
                ", ".join(x for x in (loc.get("city"), loc.get("country")) if x)
                for loc in p.get("locations") or []
            )
        )
        salary = p.get("salary") or {}
        period = _PERIOD.get(str(p.get("payment") or "").upper())
        paid = period and (salary.get("min") is not None or salary.get("max") is not None)
        url = JOB_URL.format(board=board, id=p["id"])
        return JobStub(
            source="scalis",
            url=url,
            title=(p.get("title") or "").strip(),
            company=company,
            location=where,
            description=html_to_text(body),
            posted_at=from_iso(p.get("createdAt")),
            ats="scalis",
            apply_url=url,
            remote=mode(p.get("workplace")) or remote_from_text(p.get("title"), where),
            salary_min=salary.get("min") if paid else None,
            salary_max=salary.get("max") if paid else None,
            salary_currency=salary.get("currency") if paid else None,
            salary_interval=period if paid else None,
            extra={
                "board": board,
                "id": p["id"],
                "employment": p.get("employment"),
                "skills": p.get("skills") or [],
            },
        )
