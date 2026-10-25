"""Aviasales careers (vacancies-app.aviasales.ru): a JSON list of vacancies and, per vacancy, the
site's own page-data route with the body. Single-company plugin. Logic adapted from freehire
(MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.companies._f41 import ats_of, remote_ru
from linkit_all.sources.http import Http

LIST = "https://vacancies-app.aviasales.ru/api/vacancies"
# The route id is literal text "(id)" (percent-encoded), not the numeric id.
DETAIL = (
    "https://vacancies-app.aviasales.ru/about/vacancies/{id}"
    "?__loader=about/vacancies/%28id%29/page&__ssrDirect=true"
)
JOB = "https://www.aviasales.ru/about/vacancies/{id}"
_ID = re.compile(r"/vacancies/(\d+)")


class Aviasales(Source):
    name = "aviasales"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "aviasales:vacancies")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        rows = await http.get_json(LIST)
        stubs = [s for r in rows if isinstance(r, dict) and (s := self.stub(r))]
        if start_page == 0 and stubs:
            yield stubs

    def stub(self, v: dict[str, Any]) -> JobStub | None:
        title = " ".join(str(v.get("position") or "").split())
        if not v.get("id") or not title:
            return None
        url = JOB.format(id=v["id"])
        place = str(v.get("workPlace") or "").strip()
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Aviasales",
            location=place,
            ats=ats_of(url, self.name),
            apply_url=url,
            remote=remote_ru(place),
            extra={"id": str(v["id"])},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _ID.search(stub.url)
        if stub.description or not m:
            return stub
        v = (await http.get_json(DETAIL.format(id=m[1]))).get("vacancy") or {}
        body = "".join(
            str(v.get(k) or "") for k in ("description", "todo", "requirements", "conditions")
        )
        return stub.model_copy(update={"description": strip_html(body)})
