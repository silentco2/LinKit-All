"""Dodo Brands careers (dodoteam.ru): the site's backend lists vacancies grouped by speciality and
serves each body as content blocks. Single-company plugin (the company is the brand of the
vacancy). Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.companies._f41 import ats_of, remote_ru
from linkit_all.sources.http import Http

API = "https://job-site-backend.dodo-ai-platform.io/api/v1"
JOB = "https://dodoteam.ru/vacancy/{id}"
# The API labels some brands by team: "Engineering" is Dodo's tech unit.
RENAMED = {"Engineering": "Dodo Engineering"}
BODY = {"vacancy_text", "vacancy_expectation", "vacancy_you_will", "vacancy_benefits"}
_ID = re.compile(r"/vacancy/(\d+)")


class Dodo(Source):
    name = "dodo"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "dodo:vacancies")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        data = await http.get_json(f"{API}/vacancies")
        items = [i for g in data.get("data") or [] for i in g.get("items") or []]
        stubs = [s for i in items if (s := self.stub(i))]
        if start_page == 0 and stubs:
            yield stubs

    def stub(self, v: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(v.get("position") or "").split())
        if not v.get("id") or not title:
            return None
        brand = str(v.get("brand") or "").strip() or "Dodo"
        url = JOB.format(id=v["id"])
        place = str(v.get("vacancy_location") or "").strip()
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=RENAMED.get(brand, brand),
            location=place,
            ats=ats_of(url, self.name),
            apply_url=url,
            remote=remote_ru(place, " ".join(v.get("work_format") or [])),
            extra={"id": str(v["id"])},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        if stub.description or not m:
            return stub
        data = await http.get_json(f"{API}/pages/vacancy/{m[1]}")
        blocks = ((data.get("data") or {}).get("page") or {}).get("content") or []
        html = "".join(
            (b.get("data") or {}).get("text") or "" for b in blocks if b.get("type") in BODY
        )
        return stub.model_copy(update={"description": strip_html(html)})
