"""VK's careers API (team.vk.company): a paged list with no body; the description is the
schema.org `description` of each vacancy's server-rendered page. VK's edge rate-limits bursts, so
those pages are read one at a time with a pause (a page that is challenged anyway stays without a
description and is retried by the next enrich run). A single-company plugin, not an ATS. Logic
adapted from freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f13 import get_page
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import paged, strip_html
from linkit_all.sources.http import Http

LIST = "https://team.vk.company/career/api/v2/vacancies/?limit={limit}&offset={offset}"
VACANCY = "https://team.vk.company/vacancy/{id}/"
PAGE = 50
_ID = re.compile(r"/vacancy/(\d+)")


def parse_item(it: dict[str, Any]) -> JobStub | None:
    if not (it.get("id") and it.get("title")):
        return None
    town = (it.get("town") or {}).get("name") or ""
    url = VACANCY.format(id=it["id"])
    return JobStub(
        source="vk",
        ats="vk",
        url=url,
        title=" ".join(str(it["title"]).split()),
        company="VK",
        location=town,
        apply_url=url,
        remote="remote" if it.get("remote") else None,
        extra={"id": str(it["id"])},
    )


class VK(Source):
    name = "vk"
    kind = "company"
    detail_pause = 5.0  # seconds between vacancy pages; VK challenges faster readers

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "vk:careers", board="team.vk.company")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.get_json(LIST.format(limit=PAGE, offset=offset))
            return data.get("results") or [], data.get("count")

        async for items in paged(fetch, PAGE, start_page):
            yield [s for it in items if (s := parse_item(it))]

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not _ID.search(stub.url):
            return stub
        await asyncio.sleep(self.detail_pause)
        node = LexborHTMLParser((await get_page(http, stub.url)).text).css_first(
            '[itemprop="description"]'
        )
        text = strip_html(node.html or "") if node else ""
        return stub.model_copy(update={"description": text}) if text else stub
