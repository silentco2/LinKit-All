"""Yandex Crowd's vacancy catalogue (crowd.yandex.ru/vacancies), the gig and support arm of Yandex:
the landing page inlines every posting, grouped by direction, as one JSON array in a
`<script id="data">` tag. The array is stale (taken-down postings stay in it, flagged
`available: false`), so only available ones are kept. A single-company plugin, not an ATS. Logic
adapted from freehire (MIT)."""

import json
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import get_page, strip_html
from linkit_all.sources.http import Http

PAGE = "https://crowd.yandex.ru/vacancies"
HOST = "https://crowd.yandex.ru/"


def work_mode(remotely: str | None) -> Remote | None:
    """The `remotely` tag: "удалённо" (remote) or "локально" (onsite)."""
    r = (remotely or "").lower()
    return "remote" if "удал" in r else "onsite" if "локал" in r else None


def parse_page(html: str) -> list[JobStub]:
    node = LexborHTMLParser(html).css_first("script#data")
    try:
        groups = json.loads(node.text(deep=True)) if node else []
    except ValueError:
        return []
    stubs = []
    for g in groups if isinstance(groups, list) else []:
        for v in g.get("vacancies") or []:
            url = str(v.get("url") or "").strip()
            slug = url.removeprefix(HOST).removeprefix("http://crowd.yandex.ru/").strip("/")
            title = " ".join(strip_html(str(v.get("title") or "")).split())
            if not (v.get("available") and slug and title):
                continue  # a taken-down posting's page 404s
            stubs.append(
                JobStub(
                    source="yandexcrowd",
                    ats="yandexcrowd",
                    url=url,
                    title=title,
                    company="Yandex Crowd",
                    description=strip_html(str(v.get("description") or "")),
                    apply_url=url,
                    remote=work_mode((v.get("tags") or {}).get("remotely")),
                    extra={"id": slug},
                )
            )
    return stubs


class YandexCrowd(Source):
    name = "yandexcrowd"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "yandexcrowd:vacancies", board=PAGE)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        yield parse_page((await get_page(http, PAGE)).text)
