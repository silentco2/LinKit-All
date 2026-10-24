"""Recrutei (jobs.recrutei.com.br), a Brazilian ATS: a per-tenant POST lists every posting by
department and each posting page carries the description. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from linkit_all.sources.ats._f13 import get_page, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.text import html_to_text

API = "https://api.recrutei.com.br/api/v2/vacancies/per-departments/{board}"
_UNSTATED = "Não informado"
# The labor regime says more than the page's constant FULL_TIME: CLT = employee, PJ = contractor.
_REGIME = {"CLT": "full_time", "Pessoa Jurídica": "contract"}


def places(value: Any) -> str:
    """The item's `location`: a list of strings, or a bare string (the "not stated" placeholder
    included, which means no location)."""
    parts = [value] if isinstance(value, str) else value or []
    return ", ".join(p for p in parts if p and p != _UNSTATED)


def posted(value: Any) -> datetime | None:
    try:
        return datetime.strptime(str(value), "%d/%m/%Y %H:%M:%S")
    except ValueError:
        return None


class Recrutei(Source):
    name = "recrutei"
    kind = "ats"
    url_patterns = (re.compile(r"jobs\.recrutei\.com\.br/([\w-]+)", re.I),)
    cdx_hosts = ("jobs.recrutei.com.br/*",)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        data = (await http.post_json(API.format(board=task.board), {"search": ""})).get(
            "data"
        ) or {}
        items = [i for dept in data.get("vacancies") or [] for i in dept.get("items") or []]
        # The only completeness signal this endpoint has: the declared total.
        if len(items) != data.get("total"):
            raise ValueError(
                f"recrutei: {task.board}: declared total {data.get('total')} "
                f"disagrees with {len(items)} listed postings"
            )
        company = name_from_slug(task.board)
        yield [self.stub(i, task.board, company) for i in items if i.get("public_link")]

    @staticmethod
    def stub(i: dict[str, Any], board: str, company: str) -> JobStub:
        where = places(i.get("location"))
        title = (i.get("title") or "").strip()
        return JobStub(
            source="recrutei",
            url=i["public_link"],
            title=title,
            company=i.get("company_name") or company,
            location=where,
            ats="recrutei",
            apply_url=i["public_link"],
            remote=remote_from_text(title, where),
            extra={
                "board": board,
                "id": str(i.get("id")),
                "employment": _REGIME.get(i.get("regime") or ""),
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        resp = await get_page(http, stub.url)
        found = job_postings(resp.text)[:1]
        if not found:
            return stub
        return stub.model_copy(
            update={
                "description": html_to_text(found[0].get("description") or ""),
                "posted_at": posted(found[0].get("datePosted")) or stub.posted_at,
            }
        )
