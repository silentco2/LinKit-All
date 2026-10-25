"""MTS Link careers (mts-link.ru): the Huntflow-backed JSON API on the company's own site, a list
of open positions and a detail request per position for the body. A single-company plugin, not
an ATS. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import json_or_none
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import ru_mode, sections
from linkit_all.sources.tasks import careers_task

LIST = "https://mts-link.ru/api/huntflow/vacancies"
DETAIL = "https://mts-link.ru/api/huntflow/vacancy/{id}"
JOB = "https://mts-link.ru/vacancies/{id}/"
_ID = re.compile(r"/vacancies/(\d+)")


class MtsLink(Source):
    name = "mtslink"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one page holds every position
            return
        items = await http.get_json(LIST)
        yield [s for it in items if it.get("state") == "OPEN" and (s := self.stub(it))]

    def stub(self, it: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(it.get("position") or "").split())
        if not it.get("id") or not title or it.get("hidden"):
            return None
        created = it.get("created") or {}
        try:  # "2026-09-03 17:59:10.000000" plus its "+03:00" offset
            posted = from_iso(f"{created['date']}{created.get('timezone', '')}")
        except (KeyError, ValueError):
            posted = None
        url = JOB.format(id=it["id"])
        return JobStub(
            source=self.name,
            url=url,
            apply_url=url,
            title=title,
            company="MTS Link",
            posted_at=posted,
            ats=self.name,
            remote=ru_mode(it.get("workFormat")),
            extra={"mtslink_id": it["id"]},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        d = await json_or_none(http, DETAIL.format(id=m[1])) if m else None
        body = sections(
            ("", (d or {}).get("body")),
            ("", (d or {}).get("requirements")),
            ("", (d or {}).get("conditions")),
        )
        return stub.model_copy(update={"description": body}) if body else stub
