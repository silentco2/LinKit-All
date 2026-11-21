"""Jobindex (jobindex.dk), Denmark's largest job board. Each search query is read from the result
page's own data (`var Stash = {...}`, 20 jobs a page); the card text is the description, with no
request per job (maintainer 2026-11-20). The stable `/vis-job/<id>` page is the job's address;
the employer's own application form is the apply URL when the card names one."""

import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote_plus

from aiolimiter import AsyncLimiter

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import fetch_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, safe_date
from linkit_all.sources.tasks import query_tasks
from linkit_all.sources.text import html_to_text

BASE = "https://www.jobindex.dk"
MAX_PAGES = 50  # the site's own ceiling (`max_page`)
INTERVAL = 1.0  # seconds between requests
_STASH = "var Stash = "


def results(page: str) -> tuple[list[dict[str, Any]], int]:
    """(the jobs on a result page, how many pages the search has); ([], 0) when there are none."""
    at = page.find(_STASH)
    if at < 0:
        return [], 0
    try:
        data, _ = json.JSONDecoder().raw_decode(page, at + len(_STASH))
        found = data["jobsearch/result_app/list"]["storeData"]["searchResponse"]
    except (ValueError, KeyError, TypeError):
        return [], 0
    return list(found.get("results") or []), int(found.get("total_pages") or 0)


def stub(r: dict[str, Any]) -> JobStub | None:
    url, title = r.get("share_url") or "", clean(r.get("headline"))
    if not url.startswith(f"{BASE}/") or not title:
        return None
    company = clean(r.get("companytext") or (r.get("company") or {}).get("name")) or "Unknown"
    cities = [a.get("city") for a in r.get("addresses") or [] if a.get("city")]
    return JobStub(
        source="jobindex", url=url, title=title, company=company,
        location=clean(r.get("area") or (cities[0] if cities else "")),
        description=html_to_text(r.get("html") or ""), posted_at=safe_date(r.get("firstdate")),
        apply_url=r.get("app_apply_url") or url,
        remote="remote" if r.get("home_workplace") else None,
        extra={"id": r.get("tid"), "deadline": r.get("lastdate")},
    )  # fmt: skip


class Jobindex(Source):
    name = "jobindex"
    kind = "board"
    label = "Jobindex"
    region = "Denmark"

    def __init__(self) -> None:
        self._pace = AsyncLimiter(1, INTERVAL)

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return query_tasks(self.name, cfg, locations=False)  # a Danish board: our rules place it

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        count = 0
        for page in range(start_page + 1, MAX_PAGES + 1):
            url = f"{BASE}/jobsoegning?q={quote_plus(task.query)}" + (f"&page={page}" * (page > 1))
            async with self._pace:
                html = await fetch_html(http, url)
            rows, pages = results(html or "")
            stubs = [s for r in rows if (s := stub(r))][: task.limit - count]
            if not stubs:
                return
            count += len(stubs)
            yield stubs
            if count >= task.limit or page >= pages:
                return
