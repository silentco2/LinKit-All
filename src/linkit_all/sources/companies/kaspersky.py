"""Kaspersky's careers site (careers.kaspersky.ru): a Next.js app whose listing pages server-render
their data into the RSC flight (the site's /api/ is not used); `fetch_details` reads the posting
page for the body. A single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, strip_html
from linkit_all.sources.http import Http

HOST = "careers.kaspersky.ru"
PAGE = 13  # fixed by the site; size/limit parameters are ignored
LIST = "https://{host}/vacancies?page={page}"  # 0-based
JOB = "https://{host}/vacancy/{id}"
MAX_PAGES = 50
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
_TOTAL = re.compile(r'"totalCount":(\d+)')
# The bare field name also keys an i18n string earlier in the flight: anchor on the array.
_KEY = '"vacancies":['


def flight(html: str) -> str:
    """The page's RSC flight: every pushed chunk (a JS string literal, JSON-compatible) joined."""
    return "".join(json.loads(m[1]) for m in _PUSH.finditer(html))


def listing(html: str) -> tuple[list[dict[str, Any]], int]:
    """(postings, catalogue size) from a listing page; a flight without the array is an error."""
    data = flight(html)
    at = data.find(_KEY)
    if at < 0:
        raise ValueError("kaspersky: listing array not found in the flight")
    items, end = json.JSONDecoder().raw_decode(data, at + len(_KEY) - 1)
    m = _TOTAL.search(data, end)
    return items, int(m[1]) if m else 0


def _label(named: dict[str, Any]) -> str:
    """English name when there is one (the plain name is Russian for Russian places)."""
    return (named.get("engName") or named.get("name") or "").strip()


class Kaspersky(Source):
    name = "kaspersky"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "kaspersky:careers", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        found = start_page * PAGE
        for page in range(start_page, MAX_PAGES):
            items, total = listing(
                (await get_page(http, LIST.format(host=task.board, page=page))).text
            )
            if not items:
                return
            yield [s for it in items if (s := self.stub(it, task.board))]
            found += len(items)
            if found >= total:
                return

    def stub(self, it: dict[str, Any], host: str) -> JobStub | None:
        jid = str(it.get("jobReqId") or "").strip()
        title = next((t["title"].strip() for t in it.get("titles") or [] if t.get("title")), "")
        if not jid or not title:
            return None
        url = JOB.format(host=host, id=jid)
        cities = dict.fromkeys(_label(c) for c in it.get("cities") or [])
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Kaspersky",
            location=", ".join(c for c in cities if c),
            ats=self.name,
            apply_url=url,
            extra={
                "id": jid,
                "skills": [_label(s) for s in it.get("skills") or []],
                "categories": [_label(c) for c in it.get("categories") or []],
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        resp = await get_page(http, stub.url)
        if "/vacancy/" not in str(resp.url):  # a closed requisition redirects to the listing
            return stub
        body = LexborHTMLParser(resp.text).css_first('[data-testid="vacancy-body"]')
        return (
            stub.model_copy(update={"description": strip_html(body.html or "")}) if body else stub
        )
