"""Get on Board (getonbrd.com), a LatAm tech job board. Its public API has no global jobs list, so
this walks the open per-category lists and looks up each employer's name once per run.
Logic adapted from freehire (MIT)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task, from_epoch_ms
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.tasks import feed_task

API = "https://www.getonbrd.com/api/v0"
JOB_URL = "https://www.getonbrd.com/jobs/{}"
PAGE = 50
MAX_PAGES = 100  # per category; a runaway guard
_MODES: dict[str, Remote] = {
    "fully_remote": "remote", "remote": "remote", "hybrid": "hybrid",
    "no_remote": "onsite", "on_site": "onsite", "onsite": "onsite",
}  # fmt: skip


class GetOnBrd(Source):
    name = "getonbrd"
    kind = "aggregator"

    def __init__(self) -> None:
        self._companies: dict[str, str] = {}  # employer id -> name, for the run

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        cats = (await http.get_json(f"{API}/categories")).get("data") or []
        seen: set[str] = set()  # a posting can sit in several categories
        index = count = 0  # index: one yielded page per (category, page); count: jobs yielded
        for cat in cats:
            for page in range(1, MAX_PAGES + 1):
                url = f"{API}/categories/{cat['id']}/jobs"
                data = await http.get_json(url, params={"per_page": PAGE, "page": page})
                rows = [r for r in data.get("data") or [] if r.get("id") and r["id"] not in seen]
                seen.update(r["id"] for r in rows)
                if rows and index >= start_page:  # on resume the skipped pages are re-read, unseen
                    stubs = await self.stubs(http, rows[: task.limit - count])
                    count += len(stubs)
                    yield stubs
                    if count >= task.limit:
                        return
                index += bool(rows)
                if page >= (data.get("meta") or {}).get("total_pages", 0) or not data.get("data"):
                    break

    async def stubs(self, http: Http, rows: list[dict[str, Any]]) -> list[JobStub]:
        ids = {self.company_id(r) for r in rows} - {""} - self._companies.keys()
        await asyncio.gather(*(self.load_company(http, i) for i in ids))
        return [self.stub(r) for r in rows]

    @staticmethod
    def company_id(row: dict[str, Any]) -> str:
        data = ((row.get("attributes") or {}).get("company") or {}).get("data") or {}
        return str(data.get("id") or "")

    async def load_company(self, http: Http, company_id: str) -> None:
        resp = await http.get(f"{API}/companies/{company_id}")
        if resp.status_code == 200:
            name = ((resp.json().get("data") or {}).get("attributes") or {}).get("name")
            if name:
                self._companies[company_id] = name

    def stub(self, row: dict[str, Any]) -> JobStub:
        a = row.get("attributes") or {}
        body = "\n\n".join(
            strip_html(a.get(k) or "") for k in ("functions", "description", "benefits") if a.get(k)
        )
        url = JOB_URL.format(row["id"])
        return JobStub(
            source=self.name,
            url=url,
            title=(a.get("title") or "").strip(),
            company=self._companies.get(self.company_id(row), "Unknown"),
            location=", ".join(a.get("countries") or []),
            description=body,
            posted_at=from_epoch_ms((a.get("published_at") or 0) * 1000),
            apply_url=url,
            remote=_MODES.get(a.get("remote_modality") or ""),
            extra={"id": row["id"]},
        )
