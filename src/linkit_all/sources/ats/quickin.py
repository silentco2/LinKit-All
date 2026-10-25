"""Quickin public careers API (api.quickin.io), a Brazilian ATS (sites at jobs.quickin.io/<slug>).
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import mode, name_from_slug
from linkit_all.sources.text import html_to_text

API = "https://api.quickin.io"
JOB_URL = "https://jobs.quickin.io/{board}/jobs/{id}"
PAGE = 100


class Quickin(Source):
    """The board is the account slug; it is resolved to the account's opaque id that keys the
    paged job list, and the list carries each posting in full."""

    name = "quickin"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.quickin\.io/([\w-]+)", re.I),)
    cdx_hosts = ("jobs.quickin.io/*",)
    parallel = 4

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        account = await http.get_json(f"{API}/public/accounts/{task.board}")
        account_id = account.get("_id")
        if not account_id:
            raise ValueError(f"quickin: account {task.board} has no id")
        company = account.get("name") or name_from_slug(task.board)
        page = start_page + 1
        while True:
            data = await http.get_json(f"{API}/public/{account_id}/jobs?page={page}&limit={PAGE}")
            docs = data.get("docs") or []
            yield [
                self.stub(d, task.board, company)
                for d in docs
                if d.get("publicate") == "published" and d.get("_id")
            ]
            # Stop at the reported last page; if `pages` is missing, a short page ends it.
            pages = data.get("pages") or 0
            if (page >= pages) if pages else (len(docs) < PAGE):
                return
            page += 1

    @staticmethod
    def stub(d: dict[str, Any], board: str, company: str) -> JobStub:
        where = ", ".join(p for p in (d.get("city"), d.get("region"), d.get("country")) if p)
        url = d.get("career_url") or JOB_URL.format(board=board, id=d["_id"])
        body = "\n\n".join(
            t
            for t in (
                html_to_text(d.get("description") or ""),
                html_to_text(d.get("requirements") or ""),
            )
            if t
        )
        return JobStub(
            source="quickin",
            url=url,
            title=(d.get("title") or "").strip(),
            company=company,
            location=where,
            description=body,
            posted_at=from_iso(d.get("created_at")),
            ats="quickin",
            apply_url=url,
            remote=mode(d.get("workplace_type")) or remote_from_text(where),
            extra={"board": board, "id": d["_id"]},
        )
