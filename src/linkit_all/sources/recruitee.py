"""Recruitee public offers API (one call returns every offer with its description)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://{board}.recruitee.com/api/offers/"


class Recruitee(Source):
    name = "recruitee"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.recruitee\.com", re.I),)
    cdx_hosts = ("*.recruitee.com",)
    parallel = 4  # public JSON API; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        data = await http.get_json(API.format(board=task.board))
        yield [
            self.stub(j, task.board)
            for j in data.get("offers") or []
            if j.get("status", "published") == "published"
        ]

    @staticmethod
    def stub(j: dict[str, Any], board: str) -> JobStub:
        salary = j.get("salary") or {}
        remote: Remote | None = (
            "remote" if j.get("remote") else "hybrid" if j.get("hybrid") else None
        ) or ("onsite" if j.get("on_site") else None)
        parts = [html_to_text(j.get(k) or "") for k in ("description", "requirements")]
        url = j.get("careers_url") or f"https://{board}.recruitee.com/o/{j['slug']}"
        return JobStub(
            source="recruitee",
            url=url,
            title=j["title"],
            company=j.get("company_name") or board.replace("-", " ").title(),
            location=j.get("location") or "",
            description="\n\n".join(p for p in parts if p),
            # timestamps look like "2026-10-15 09:31:36 UTC"
            posted_at=from_iso((j.get("published_at") or "").replace(" UTC", "+00:00")),
            ats="recruitee",
            apply_url=j.get("careers_apply_url") or url,
            remote=remote,
            salary_min=salary.get("min"),
            salary_max=salary.get("max"),
            salary_currency=salary.get("currency"),
            salary_interval=salary.get("period"),
            extra={"board": board, "id": j["id"], "guid": j.get("guid")},
        )
