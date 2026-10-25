"""Lesta Games' careers site (join.lesta.team): a JSON listing (/filters?offset=N, 15 a page, with
the catalogue total) carries every field but the body, which `fetch_details` reads from the
vacancy page. The site hands out a session cookie by redirect; the shared client keeps it. A
single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f13 import get_page
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import paged, strip_html
from linkit_all.sources.companies._f42 import remote_ru
from linkit_all.sources.http import Http

HOST = "join.lesta.team"
PAGE = 15
LIST = "https://{host}/filters?offset={offset}"
JOB = "https://{host}/vacancy/{slug}/{id}"
_JOB_URL = re.compile(r"/vacancy/[^/?#]+/\d+")


class Lesta(Source):
    name = "lesta"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "lesta:vacancies", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.get_json(LIST.format(host=task.board, offset=offset))
            return data.get("vacancies") or [], data.get("total")

        async for items in paged(fetch, PAGE, start_page):
            yield [s for v in items if (s := self.stub(v, task.board))]

    def stub(self, v: dict[str, Any], host: str) -> JobStub | None:
        title = " ".join((v.get("title") or "").split())
        if not v.get("id") or not v.get("slug") or not title:
            return None
        url = JOB.format(host=host, slug=v["slug"], id=v["id"])
        city = (v.get("location_city") or "").strip()
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Lesta Games",
            location=city,
            ats=self.name,
            apply_url=url,
            remote=remote_ru(city),
            extra={
                "id": str(v["id"]),
                "skills": v.get("tags_skills") or [],
                "experience": v.get("exp_range") or [],
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not _JOB_URL.search(stub.url):
            return stub
        tree = LexborHTMLParser((await get_page(http, stub.url)).text)
        # company intro, project intro, the role, the offer; the skills block repeats the tags
        blocks = [b.html or "" for b in tree.css(".vacancy__item") if not b.css_first(".tags")]
        return stub.model_copy(update={"description": strip_html("".join(blocks))})
