"""Lamoda's public job API (job.lamoda.ru): an offset-paged compact list, then one detail request
per posting for the body. A single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import paged, strip_html
from linkit_all.sources.companies._f42 import remote_ru
from linkit_all.sources.http import Http

HOST = "job.lamoda.ru"
PAGE = 100
LIST = "https://{host}/api/hr/vacancies/compact?pagination%5Blimit%5D={limit}&pagination%5Bstart%5D={start}"
DETAIL = "https://{host}/api/hr/vacancies/{id}"
_ID = re.compile(r"-(\d+)/?$")  # slugs read "moskva/menedzher-2466"
_BODY = ("introduction", "duties", "requirements", "conditions")


class Lamoda(Source):
    name = "lamoda"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "lamoda:vacancies", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.get_json(LIST.format(host=task.board, limit=PAGE, start=offset))
            return data.get("data") or [], (data.get("meta") or {}).get("total")

        async for items in paged(fetch, PAGE, start_page):
            yield [s for v in items if (s := self.stub(v, task.board))]

    def stub(self, v: dict[str, Any], host: str) -> JobStub | None:
        title = " ".join((v.get("name") or "").split())
        if not v.get("id") or not v.get("slug") or not title:
            return None
        url = f"https://{host}/vacancies/{v['slug']}"
        location = ((v.get("location") or {}).get("name") or "").strip()
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Lamoda",
            location=location,
            posted_at=from_iso(v.get("externalPublicationDate")),
            ats=self.name,
            apply_url=url,
            remote=remote_ru(location),
            extra={"id": str(v["id"])},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        # The enrich stage rebuilds the stub from the DB: only the url is the vendor's.
        if not (m := _ID.search(stub.url)):
            return stub
        data = await http.get_json(DETAIL.format(host=urlsplit(stub.url).netloc, id=m[1]))
        attrs = (data.get("data") or {}).get("attributes") or {}
        # Retail vacancies leave the four fields empty and keep the whole body in `common`.
        body = "".join(attrs.get(k) or "" for k in _BODY) or attrs.get("common") or ""
        return stub.model_copy(update={"description": strip_html(body)})
