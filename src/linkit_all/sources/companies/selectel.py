"""Selectel careers (selectel.ru/careers): a Nuxt site whose listing page carries every vacancy in
its devalue-encoded `__NUXT_DATA__` payload and whose vacancy pages carry the body the same way.
A single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import get_page, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import unflatten

LIST = "https://selectel.ru/careers/all/"
VACANCY = "https://selectel.ru/careers/all/vacancy/{id}/"
_ID = re.compile(r"/careers/all/vacancy/(\d+)")


def payload(html: str) -> Any:
    """The page's `__NUXT_DATA__` as plain nested values; None when it is missing or unreadable."""
    node = LexborHTMLParser(html).css_first("script#__NUXT_DATA__")
    try:
        raw = json.loads(node.text(deep=True)) if node else None
    except ValueError:
        return None
    return unflatten(raw) if isinstance(raw, list) else None


def find_map(node: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
    """The first object, depth first, that has all of `keys` (walking keeps this working when
    Nuxt nests its store differently)."""
    if isinstance(node, dict):
        if all(k in node for k in keys):
            return node
        node = list(node.values())
    if isinstance(node, list):
        for v in node:
            if (found := find_map(v, keys)) is not None:
                return found
    return None


def parse_list(html: str) -> list[JobStub]:
    store = find_map(payload(html), ("item_count", "items")) or {}
    stubs = []
    for it in store.get("items") or []:
        if not (isinstance(it, dict) and it.get("id") and it.get("title")):
            continue
        city = (it.get("city") or {}).get("name") or ""
        url = VACANCY.format(id=it["id"])
        stubs.append(
            JobStub(
                source="selectel",
                ats="selectel",
                url=url,
                title=" ".join(str(it["title"]).split()),
                company="Selectel",
                location=city,
                posted_at=from_iso(it.get("published_at")),
                apply_url=url,
                # The site only says remote work is on offer, never what the alternative is.
                remote="remote" if it.get("is_remote_available") else remote_from_text(city),
                extra={"id": str(it["id"])},
            )
        )
    return stubs


class Selectel(Source):
    name = "selectel"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "selectel:careers", board="selectel.ru")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one page lists every vacancy
            return
        yield parse_list((await get_page(http, LIST)).text)

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not _ID.search(stub.url):
            return stub
        vac = find_map(payload((await get_page(http, stub.url)).text), ("detailed_desc",))
        if vac is None:
            return stub
        body = "".join(str(vac.get(k) or "") for k in ("short_desc", "detailed_desc", "conditions"))
        return stub.model_copy(update={"description": strip_html(body)}) if body.strip() else stub
