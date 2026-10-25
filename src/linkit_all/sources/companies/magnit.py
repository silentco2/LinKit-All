# ruff: noqa: RUF001
"""Magnit Tech (magnit.tech), the IT arm of the Magnit retail group: a keyless JSON list plus one
detail request per vacancy for the body. A single-company plugin, not an ATS. Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.companies._f43 import (
    careers_task,
    distinct,
    json_or_none,
    ru_mode,
    sections,
)
from linkit_all.sources.http import Http

LIST = "https://magnit.tech/api/v1/vacancy?page={page}&per_page=50"
DETAIL = "https://magnit.tech/api/v1/vacancy/{id}"
JOB = "https://magnit.tech/vacancies/{id}"
MAX_PAGES = 20
_ID = re.compile(r"/vacancies/(\d+)")
# Body fields in the order the site shows them, with the employer's own headings.
_BODY = (
    ("about_product", "О продукте"),
    ("tasks", "Задачи"),
    ("skills", "Требования"),
    ("extra_skills", "Будет плюсом"),
    ("offer", "Мы предлагаем"),
)


class Magnit(Source):
    name = "magnit"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(LIST.format(page=page))
            items = data.get("results") or []
            if items:
                yield [s for it in items if (s := self.stub(it))]
            if not items or not (data.get("meta") or {}).get("has_more_pages"):
                return

    def stub(self, it: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(it.get("title") or "").split())
        if not it.get("id") or not title:
            return None
        formats = [f.get("name") for f in it.get("work_formats") or []]
        url = JOB.format(id=it["id"])
        return JobStub(
            source=self.name,
            url=url,
            apply_url=url,
            title=title,
            company="Magnit Tech",
            # The places are in the work-format labels; `location` is mostly null.
            location=distinct([it.get("location"), *formats]),
            ats=self.name,
            remote=ru_mode(*formats),
            extra={
                "magnit_id": it["id"],
                "internship": bool(it.get("is_internship")),
                "skills": [t.get("name") for t in it.get("technologies") or [] if t.get("name")],
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        data = await json_or_none(http, DETAIL.format(id=m[1])) if m else None
        d = (data or {}).get("results") or {}
        if not d.get("is_published") or str(d.get("status") or "").lower() != "active":
            return stub  # closed between the list and now
        body = sections(("", d.get("description")), *((h, d.get(k)) for k, h in _BODY))
        return stub.model_copy(update={"description": body})
