"""Traffit career sites ({board}.traffit.com): the public advert list returns each posting in
full, 100 to a page. Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import paged, strip_html
from linkit_all.sources.http import Http

_SIZE = 100  # the endpoint's maximum


def _location(geo: Any) -> str:
    """The JSON string in `geolocation` as "Warszawa, Mazowieckie, Polska"; empty when odd."""
    try:
        data = json.loads(geo) if isinstance(geo, str) and geo else {}
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    parts = (str(data.get(k) or "").strip() for k in ("locality", "region1", "country"))
    return ", ".join(p for p in parts if p)


class Traffit(Source):
    name = "traffit"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.traffit\.com", re.I),)
    cdx_hosts = ("*.traffit.com",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = f"https://{task.board.lower()}.traffit.com"

        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.get_json(f"{host}/public/an/list/?limit={_SIZE}&offset={offset}")
            return data.get("items") or [], data.get("count")

        async for items in paged(fetch, _SIZE, start_page, max_pages=500):
            yield [s for item in items if (s := self._stub(item, task.board))]

    def _stub(self, item: dict[str, Any], board: str) -> JobStub | None:
        advert = item.get("advertId") or item.get("advertPublishId")
        title = " ".join(str(item.get("title") or item.get("name") or "").split())
        url = str(item.get("url") or "").strip()
        if not (advert and title and url):
            return None
        start = item.get("validStart")
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=name_from_slug(board),
            location=_location(item.get("geolocation")),
            description=strip_html(item.get("description") or ""),
            posted_at=datetime.fromtimestamp(start, UTC).replace(tzinfo=None) if start else None,
            ats=self.name,
            apply_url=url,
            extra={"board": board, "id": str(advert)},
        )
