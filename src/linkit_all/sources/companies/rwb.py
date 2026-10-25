"""Wildberries & Russ careers (career.rwb.ru): the public vacancy API behind the site, a paged
list and a detail request per vacancy for the body. A single-company plugin, not an ATS. Logic
adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import paged
from linkit_all.sources.companies._f43 import careers_task, json_or_none, ru_mode, sections
from linkit_all.sources.http import Http

LIST = "https://career.rwb.ru/crm-api/api/v1/pub/vacancies?limit={limit}&offset={offset}"
DETAIL = "https://career.rwb.ru/crm-api/api/v1/pub/vacancies/{id}"
JOB = "https://career.rwb.ru/vacancies/{id}"
PAGE = 200
_ID = re.compile(r"/vacancies/(\d+)")


class Rwb(Source):
    name = "rwb"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            data = (await http.get_json(LIST.format(limit=PAGE, offset=offset))).get("data") or {}
            return data.get("items") or [], (data.get("range") or {}).get("count")

        async for items in paged(fetch, PAGE, start_page):
            yield [s for it in items if (s := self.stub(it))]

    def stub(self, it: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(it.get("name") or "").split())
        if not it.get("id") or not title:
            return None
        formats = [e.get("title") for e in it.get("employment_types") or []]
        url = JOB.format(id=it["id"])
        return JobStub(
            source=self.name,
            url=url,
            apply_url=url,
            title=title,
            company="Wildberries & Russ",
            location=it.get("city_title") or "",
            ats=self.name,
            remote=ru_mode(*formats),
            extra={"rwb_id": it["id"], "direction": it.get("direction_title")},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        d = ((await json_or_none(http, DETAIL.format(id=m[1]))) or {}).get("data") if m else None
        d = d or {}
        body = sections(
            ("", d.get("description")),
            ("", "\n".join(d.get("duties_arr") or [])),
            ("", "\n".join(d.get("requirements_arr") or [])),
            ("", "\n".join(d.get("conditions_arr") or [])),
        )
        return stub.model_copy(update={"description": body}) if body else stub
