"""Yandex's public jobs API (yandex.ru/jobs): a cursor-paged publication list with no body, so
each vacancy's description comes from its own detail request. Redirects and hiring events in the
list are not vacancies and are dropped. The task's board is the host suffix ("ru" or "com").
A single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlsplit

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f16 import GONE
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.companies._f41 import limited, remote_ru
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

LIST = "https://yandex.{tld}/jobs/api/publications"
DETAIL = "https://yandex.{tld}/jobs/api/publications/{id}"
VACANCY = "https://yandex.{tld}/jobs/vacancies/{slug}"
MAX_PAGES = 500  # a throttled API can hand back a cursor that never ends


def cursor_of(next_url: str | None) -> str:
    """The `cursor` of a next-page URL (it names an internal host; only the cursor is reused)."""
    return (parse_qs(urlsplit(next_url or "").query).get("cursor") or [""])[0]


def is_vacancy(it: dict[str, Any]) -> bool:
    return not (it.get("redirect_url") or it.get("fast_track")) and bool(
        it.get("id") and it.get("title") and it.get("publication_slug_url")
    )


def parse_item(it: dict[str, Any], d: dict[str, Any], tld: str) -> JobStub:
    vac = it.get("vacancy") or {}
    cities = [c.get("name") for c in vac.get("cities") or [] if c.get("name")]
    modes = [f"{m.get('slug') or ''} {m.get('name') or ''}" for m in vac.get("work_modes") or []]
    keys = ("short_summary", "duties", "key_qualifications", "additional_requirements")
    body = "".join(str(d.get(k) or "") for k in (*keys, "conditions"))
    return JobStub(
        source="yandex",
        ats="yandex",
        url=VACANCY.format(tld=tld, slug=it["publication_slug_url"]),
        title=" ".join(str(it["title"]).split()),
        company="Yandex",
        location=", ".join(cities),
        description=html_to_text(body),
        posted_at=from_iso(d.get("modified")),
        remote=remote_ru(*modes, *cities),
        extra={"id": str(it["id"]), "host": tld},
    )


class Yandex(Source):
    name = "yandex"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "yandex:ru", board="ru", limit=cfg.search.max_results_per_query)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async for page in limited(self.pages(http, task.board or "ru", start_page), task.limit):
            yield page

    async def pages(self, http: Http, tld: str, start_page: int) -> AsyncIterator[list[JobStub]]:
        """One page of stubs per list page. A resumed run walks the earlier list pages again
        (cheap: no detail requests) to reach the cursor of its page."""
        url, seen = LIST.format(tld=tld), set[str]()
        query = ""
        for n in range(MAX_PAGES):
            data = await http.get_json(url, params={"cursor": query} if query else None)
            if n >= start_page:
                items = [it for it in data.get("results") or [] if is_vacancy(it)]
                details = await asyncio.gather(*(self.detail(http, it, tld) for it in items))
                yield [parse_item(it, d, tld) for it, d in zip(items, details, strict=True) if d]
            query = cursor_of(data.get("next"))
            if not query or query in seen:
                return
            seen.add(query)

    @staticmethod
    async def detail(http: Http, it: dict[str, Any], tld: str) -> dict[str, Any]:
        """The publication's body fields; {} when its detail request fails (the vacancy is skipped,
        the next run offers it again)."""
        try:
            d = await http.get_json(DETAIL.format(tld=tld, id=it["id"]))
        except GONE:
            return {}
        return d if isinstance(d, dict) else {}
