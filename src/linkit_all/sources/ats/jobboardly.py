"""Jobboardly (jobboardly.com), a hosted job-board builder: each customer board publishes its
postings at {board}.jobboardly.com/jobs.json. List the boards as https://{board}.jobboardly.com
URLs (or `jobboardly:{board}`) in the company list. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import ats_of, last_segment, mode

LIST = "https://{}.jobboardly.com/jobs.json"
_PERIODS = {"yearly": "year", "monthly": "month", "daily": "day", "hourly": "hour"}


class Jobboardly(Source):
    """The board is the subdomain: `hire-mamas` for hire-mamas.jobboardly.com."""

    name = "jobboardly"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!(?:www|app)\.)([\w-]+)\.jobboardly\.com", re.I),)
    cdx_hosts = ("*.jobboardly.com",)
    parallel = 3

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page:
            return  # the whole board comes in one page
        rows = await http.get_json(LIST.format(task.board.lower()))
        stubs = [s for r in rows[: task.limit] if (s := self.stub(r, task.board))]
        if stubs:
            yield stubs

    def stub(self, p: dict[str, Any], board: str) -> JobStub | None:
        url = (p.get("links") or {}).get("self") or ""
        company = p.get("company") or {}
        if not (url and p.get("title") and company.get("name")):
            return None
        apply = p.get("application_link") or (p.get("application") or {}).get("url") or ""
        apply = apply if apply.startswith(("http://", "https://")) else url  # not an e-mail
        place = (company.get("location") or "").strip() or ", ".join(p.get("location_limits") or [])
        salary = self.salary(p.get("salary"))
        return JobStub(
            source=self.name,
            url=url,
            title=p["title"].strip(),
            company=company["name"].strip(),
            location=place,
            description=strip_html((p.get("description") or {}).get("html") or ""),
            posted_at=from_iso(p.get("published_at")),
            ats=ats_of(apply, self.name),
            apply_url=apply,
            remote=mode(p.get("location")),
            extra={"id": last_segment(url), "board": board, "employment": p.get("arrangement")},
            **salary,
        )

    @staticmethod
    def salary(s: dict[str, Any] | None) -> dict[str, Any]:
        """Bounds in whole units; empty when the period is unknown or the currencies disagree."""
        s = s or {}
        lo, hi = s.get("minimum") or {}, s.get("maximum") or {}
        currency = lo.get("currency_iso") or hi.get("currency_iso") or ""
        period = _PERIODS.get(s.get("schedule") or "")
        if not (period and currency and (lo or hi)):
            return {}
        if lo and hi and lo.get("currency_iso") != hi.get("currency_iso"):
            return {}
        return {
            "salary_min": round(lo["cents"] / 100) if lo.get("cents") else None,
            "salary_max": round(hi["cents"] / 100) if hi.get("cents") else None,
            "salary_currency": currency.upper(),
            "salary_interval": period,
        }
