"""Golang Jobs (golangjobs.tech), a Go-only board. Its site reads a public Supabase table with the
anon key shipped in its own app bundle; this reads the same table.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import timedelta
from math import ceil
from typing import Any

from linkit_all.core.models import utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import paged, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

HOME = "https://www.golangjobs.tech/"
POSTING = HOME + "golang-jobs/{}"
COLUMNS = (
    "id,title,company,type,description,salary_min,salary_max,salary_currency,"
    "posted_at,application_url,slug,cities(name,country)"
)
PAGE = 200
_ASSET = re.compile(r'src="/(assets/index-[\w-]+\.js)"')
# `new X("<project>.supabase.co", "<anon key>")`; only a supabase.co project is accepted.
_CLIENT = re.compile(r'"(https://[a-z0-9]{20}\.supabase\.co)"\s*,\s*"(eyJ[\w-]+\.[\w-]+\.[\w-]+)"')


class GolangJobs(Source):
    name = "golangjobs"
    kind = "aggregator"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        home = await http.get(HOME)
        home.raise_for_status()
        if not (asset := _ASSET.search(home.text)):
            raise ValueError("golangjobs: the home page names no app bundle")
        bundle = await http.get(HOME + asset[1])
        bundle.raise_for_status()
        if not (client := _CLIENT.search(bundle.text)):
            raise ValueError("golangjobs: the app bundle carries no Supabase client")
        base, key = client.groups()
        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        since = (utcnow() - timedelta(days=task.posted_within_days)).strftime("%Y-%m-%dT%H:%M:%SZ")

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            rows = await http.get_json(
                f"{base}/rest/v1/jobs",
                headers=headers,
                params={
                    "select": COLUMNS, "is_archived": "eq.false", "posted_at": f"gte.{since}",
                    "order": "posted_at.desc,id", "limit": PAGE, "offset": offset,
                },
            )  # fmt: skip
            return rows, None

        pages = max(0, ceil(task.limit / PAGE) - start_page)
        async for rows in paged(fetch, PAGE, start_page, max_pages=pages):
            if stubs := [s for r in rows if (s := self.stub(r))]:
                yield stubs

    def stub(self, r: dict[str, Any]) -> JobStub | None:
        title, company = " ".join((r.get("title") or "").split()), (r.get("company") or "").strip()
        if not (title and company and r.get("slug") and r.get("id")):
            return None
        city = r.get("cities") or {}
        place, country = (city.get("name") or "").strip(), (city.get("country") or "").strip()
        remote: Remote | None = None
        if place.lower() == "remote":  # the country then is the hiring scope
            remote = "remote"
            place = "Remote" if country.lower() in ("", "global") else f"Remote, {country}"
        else:
            place = ", ".join(p for p in (place, country) if p)
        url = POSTING.format(r["slug"])
        lo, hi = r.get("salary_min"), r.get("salary_max")
        currency = (r.get("salary_currency") or "").upper()
        priced = bool(lo or hi) and len(currency) == 3  # the currency defaults to USD on every row
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=company,
            location=place,
            description=strip_html(r.get("description") or ""),
            posted_at=from_iso(r.get("posted_at")),
            apply_url=(r.get("application_url") or "").strip() or url,
            remote=remote or remote_from_text(place),
            salary_min=lo if priced else None,
            salary_max=hi if priced else None,
            salary_currency=currency if priced else None,
            salary_interval="year" if priced else None,  # the site marks every range as yearly
            ats=self.name,
            extra={"id": r["id"]},
        )
