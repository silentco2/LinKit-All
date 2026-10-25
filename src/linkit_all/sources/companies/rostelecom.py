"""Rostelecom careers (job.rt.ru): the site's JSON vacancy API, descriptions included. A
single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.companies._f43 import careers_task, ru_mode, rub_month, sections
from linkit_all.sources.http import Http

LIST = "https://job.rt.ru/backend/api/vacancies?page={page}&size={size}"
JOB = "https://job.rt.ru/vacancy/{id}"
SIZE = 100
MAX_PAGES = 50
HYBRID_TAG = 11  # "Гибрид"


class Rostelecom(Source):
    name = "rostelecom"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page, MAX_PAGES):  # pages count from 0
            data = await http.get_json(LIST.format(page=page, size=SIZE))
            vacancies = data.get("vacancies") or []
            if not vacancies:
                return
            yield [s for v in vacancies if (s := self.stub(v))]
            if page + 1 >= (data.get("totalPages") or 0):
                return

    def stub(self, v: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(v.get("name") or "").split())
        if not v.get("id") or not title:
            return None
        location = ((v.get("city") or {}).get("name") or "").strip()
        mode: Remote | None = ru_mode(location)
        if any(t.get("id") == HYBRID_TAG for t in v.get("tags") or []):
            mode = "hybrid"
        url = JOB.format(id=v["id"])
        return JobStub(
            source=self.name,
            url=url,
            apply_url=url,
            title=title,
            company="Rostelecom",
            location=location,
            description=sections(
                ("Чем предстоит заниматься", v.get("whatWeToDo")),
                ("Что мы ожидаем", v.get("whatWeExpect")),
                ("Что мы предлагаем", v.get("whatWeOffer")),
            ),
            ats=self.name,
            remote=mode,
            extra={
                "rostelecom_id": v["id"],
                "directions": [d.get("name") for d in v.get("directions") or []],
            },
            **rub_month(v.get("salaryFrom"), v.get("salaryTo")),
        )
