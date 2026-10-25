"""Sber careers (rabota.sber.ru): the candidate API behind the site, a paged list of
publications with the body inline. A single-company plugin, not an ATS. Logic adapted from
freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import paged
from linkit_all.sources.companies._f43 import careers_task, ru_mode, sections
from linkit_all.sources.http import Http

LIST = (
    "https://rabota.sber.ru/public/app-candidate-public-api-gateway/api/v1/publications"
    "?skip={skip}&take={take}"
)
JOB = "https://rabota.sber.ru/search/{id}"
PAGE = 200


class Sber(Source):
    name = "sber"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            data = (await http.get_json(LIST.format(skip=offset, take=PAGE))).get("data") or {}
            return data.get("vacancies") or [], data.get("total")

        async for items in paged(fetch, PAGE, start_page):
            yield [s for it in items if (s := self.stub(it))]

    def stub(self, v: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(v.get("title") or "").split())
        if not v.get("internalId") or not title:
            return None
        city = (v.get("city") or "").strip()
        url = JOB.format(id=v["internalId"])
        try:
            posted = from_iso(v.get("publicationDate"))
        except ValueError:
            posted = None
        return JobStub(
            source=self.name,
            url=url,
            apply_url=url,
            title=title,
            company=(v.get("company") or "").strip() or "Sber",
            location=city,
            description=sections(
                ("", v.get("introduction")),
                ("", v.get("duties")),
                ("", v.get("requirements")),
                ("", v.get("conditions")),
            ),
            posted_at=posted,
            ats=self.name,
            remote=ru_mode(city),
            extra={"sber_id": v.get("requisitionId"), "specialization": v.get("specialization")},
        )
