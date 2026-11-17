"""Tes (www.tes.com/jobs), UK and international teaching jobs. No public API: the search page
fills itself from one public tRPC query on the same host, read here with the input shape the
page sends (every filter key is required). Pages of 50, newest first; the short teaser is the
description. Pay is kept only for a plain yearly range. Logic adapted from career-ops (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, safe_date
from linkit_all.sources.tasks import all_older, company_query_tasks, limited

SEARCH = "https://www.tes.com/jobs/api/trpc/jobs.search"
ORIGIN = "https://www.tes.com"
PAGE = 50  # any larger limit answers with no rows
MAX_PAGES = 400
_VACANCY = re.compile(r"^/jobs/vacancy/[a-z0-9][a-z0-9-]*-\d+$")
_AMOUNT = r"(£|€|HK\$|[A-Z]{3}\s*)([\d,]+(?:\.\d+)?)"
_PAY = re.compile(rf"^{_AMOUNT}(?:\s*-\s*{_AMOUNT})?\s+per\s+(?:year|annum)$", re.I)
_SIGNS = {"£": "GBP", "€": "EUR", "HK$": "HKD"}


def search_input(keywords: str, page: int) -> str:
    filters = {
        "contractTerms": [],
        "contractTypes": [],
        "subjects": [],
        "workplaces": [],
        "positions": [],
        "location": {"distance": 30, "distanceUnit": "mi"},
    }
    query = {
        "limit": PAGE,
        "filters": {
            "keywords": keywords,
            "locations": [],
            "excludedLocations": [],
            "filters": filters,
            "sort": "date",
            "page": page,
        },
        "siteCountry": "gb",
    }
    return json.dumps({"0": {"json": query}})


def pay(text: str) -> tuple[float, float, str] | None:
    """ "£31,650 - £49,084 per year" -> (31650, 49084, "GBP"); None for anything else."""
    m = _PAY.match(clean(text))
    if not m:
        return None
    cur = _SIGNS.get(m[1], m[1].strip().upper())
    if m[3] is not None and _SIGNS.get(m[3], m[3].strip().upper()) != cur:
        return None
    low = float(m[2].replace(",", ""))
    high = float(m[4].replace(",", "")) if m[4] else low
    return (low, high, cur) if 0 < low <= high else None


class Tes(Source):
    name = "tes"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return company_query_tasks(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self._pages(http, task, start_page), task.limit):
            yield page

    async def _pages(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            params = {"batch": "1", "input": search_input(task.query[:100], page)}
            body = await http.get_json(SEARCH, params=params)
            first = body[0] if isinstance(body, list) and body else {}
            if isinstance(first, dict) and first.get("error"):
                raise ValueError("tes: the search endpoint answered with an error")
            data = (((first or {}).get("result") or {}).get("data") or {}).get("json")
            rows = data.get("jobs") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise ValueError("tes: the response carries no jobs array (endpoint changed?)")
            stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
            yield stubs
            if len(rows) < PAGE or all_older(stubs, task):
                return

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        path, title = str(r.get("canonicalUrl") or ""), clean(r.get("title"))
        company = clean((r.get("employer") or {}).get("name"))
        if not (_VACANCY.match(path) and title and company):
            return None
        where = clean(r.get("displayLocation"))
        stub = JobStub(
            source=self.name,
            url=ORIGIN + path,
            title=title,
            company=company,
            location=where,
            description=clean(r.get("shortDescription")),
            posted_at=safe_date((r.get("advert") or {}).get("startDate")),
            ats=self.name,
            apply_url=ORIGIN + path,
            remote=remote_from_text(where),
            extra={
                "id": str(r.get("id") or path),
                "closes": (r.get("application") or {}).get("closeDate"),
            },
        )
        if found := pay(str((r.get("salary") or {}).get("range") or "")):
            stub.salary_min, stub.salary_max, stub.salary_currency = found
            stub.salary_interval = "year"
        return stub
