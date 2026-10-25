"""Ozon careers (career.ozon.ru): the public job API behind the site, a paged list of external
vacancies and a detail request per vacancy for the body. A single-company plugin, not an ATS.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.companies._f43 import careers_task, json_or_none, ru_mode, text_of
from linkit_all.sources.http import Http

LIST = "https://job-api.ozon.ru/v2/vacancy?page={page}&limit=50"
DETAIL = "https://job-api.ozon.ru/vacancy/{id}"
# The site's slug is "<title>-<hhId>" and only the detail names it, so the list-time URL is the
# bare id (the detail request is only for survivors of the filters).
JOB = "https://career.ozon.ru/vacancy/{id}/"
_ID = re.compile(r"/vacancy/(\d+)/?$")
MAX_PAGES = 400


class Ozon(Source):
    name = "ozon"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(LIST.format(page=page))
            stubs = [
                s
                for it in data.get("items") or []
                if it.get("vacancyType") == "external_vacancy" and (s := self.stub(it))
            ]
            yield stubs
            if page >= (data.get("meta") or {}).get("totalPages", 0):
                return

    def stub(self, it: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(it.get("title") or "").split())
        if not it.get("hhId") or not title:
            return None
        url = JOB.format(id=it["hhId"])
        return JobStub(
            source=self.name,
            url=url,
            apply_url=url,
            title=title,
            company="Ozon",
            location=it.get("city") or "",
            ats=self.name,
            remote=ru_mode(*(it.get("workFormat") or [])),
            extra={"ozon_id": it["hhId"], "department": it.get("department")},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        d = await json_or_none(http, DETAIL.format(id=m[1])) if m else None
        body = text_of((d or {}).get("descr"))
        return stub.model_copy(update={"description": body}) if body else stub
