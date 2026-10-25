"""MTS careers (job.mts.ru): the vacancy API behind the site, called with the public key the
site's own page config carries. A single-company plugin, not an ATS. Logic adapted from freehire
(MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import paged
from linkit_all.sources.companies._f43 import (
    careers_task,
    json_or_none,
    ru_mode,
    rub_month,
    sections,
)
from linkit_all.sources.http import Http

SITE = "https://job.mts.ru/"
LIST = "https://api.job.mts.ru/v1/vacancies/filtered/career"
DETAIL = "https://api.job.mts.ru/v1/vacancy/{id}"
JOB = "https://job.mts.ru/vacancy/{id}"
PAGE = 200
_KEY = re.compile(r'apiKey:"([^"]+)"')
_ID = re.compile(r"/vacancy/([^/?#]+)")


class Mts(Source):
    name = "mts"
    kind = "company"

    def __init__(self) -> None:
        self._key = ""

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def _api_key(self, http: Http) -> str:
        if not self._key:
            page = await http.get(SITE)
            page.raise_for_status()
            m = _KEY.search(page.text)
            if not m:
                raise ValueError("mts: no apiKey in the site config (page changed?)")
            self._key = m[1]
        return self._key

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        headers = {"x-api-key": await self._api_key(http)}

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            body = {"offset": offset, "limit": PAGE}
            data = (await http.post_json(LIST, body, headers=headers)).get("data") or {}
            return data.get("vacancies") or [], (data.get("pageInfo") or {}).get("total")

        async for items in paged(fetch, PAGE, start_page):
            yield [s for it in items if (s := self.stub(it))]

    def stub(self, it: dict[str, Any]) -> JobStub | None:
        info = it.get("info") or {}
        title = " ".join(str(it.get("name") or "").split())
        if not it.get("id") or not title:
            return None
        url = JOB.format(id=it["id"])
        return JobStub(
            source=self.name,
            url=url,
            apply_url=url,
            title=title,
            company=info.get("brand") or "MTS",
            location=info.get("city") or "",
            ats=self.name,
            remote=ru_mode(info.get("worktype")),
            extra={"mts_id": str(it["id"]), "category": info.get("category")},
            **rub_month(info.get("salaryMin"), info.get("salaryMax")),
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        headers = {"x-api-key": await self._api_key(http)}
        data = await json_or_none(http, DETAIL.format(id=m[1]), headers=headers) if m else None
        t = (((data or {}).get("data") or {}).get("vacancy") or {}).get("detailText") or {}
        body = sections(
            ("", t.get("descriptionOfProject")),
            ("", t.get("description")),
            ("", t.get("requirements")),
            ("", t.get("conditions")),
        )
        return stub.model_copy(update={"description": body}) if body else stub
