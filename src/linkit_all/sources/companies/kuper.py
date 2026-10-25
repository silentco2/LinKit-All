"""Kuper's public vacancy API (vacancies-api.sbermarket.ru; Kuper is SberMarket's grocery-delivery
brand): a paged feed whose pages are lists of category blocks, with the description inline. A
single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.companies._f42 import remote_ru
from linkit_all.sources.http import Http

HOST = "vacancies-api.sbermarket.ru"
API = "https://{host}/api/vacancy_pagination/?page={page}"
MAX_PAGES = 200


class Kuper(Source):
    name = "kuper"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "kuper:vacancies", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        for page in range(start_page + 1, MAX_PAGES + 1):
            data = await http.get_json(API.format(host=task.board, page=page))
            blocks = {b.get("category"): b.get("data") for b in data.get("result") or []}
            yield [s for v in blocks.get("vacancies") or [] if (s := self.stub(v))]
            if page >= ((blocks.get("pagination") or {}).get("pages") or 1):
                return

    def stub(self, v: dict[str, Any]) -> JobStub | None:
        title = " ".join((v.get("title") or "").split())
        if not v.get("id") or not title or not v.get("friendlyUrl") or not v.get("idForUrl"):
            return None
        # The site refuses other clients, so this public URL is built from the API's own fields.
        url = f"https://kuper.ru/rabota/{v['friendlyUrl']}-{v['idForUrl']}"
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Kuper",
            location=(v.get("city") or "").strip(),
            description=strip_html(v.get("description") or ""),  # the feed carries no date
            ats=self.name,
            apply_url=url,
            remote=remote_ru(" ".join(v.get("wf") or [])),
            extra={"id": v["id"], "work_format": v.get("wf")},
        )
