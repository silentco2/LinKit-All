"""Join (join.com): public JSON API, a few postings per list page and a Markdown body per posting
in a second call. Logic adapted from freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import GONE, get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import mode, name_from_slug

API = "https://join.com/api/public"
PAGE_SIZE = 5  # the API rejects anything larger with 422
_COMPANY_ID = re.compile(r'"company":\{"id":(\d+)')
_JOB_URL = re.compile(r"join\.com/companies/[\w-]+/(\d+)")
_BULLET = re.compile(r"^[ 	]*[*+-][ 	]+", re.M)
_EMPHASIS = re.compile(r"(\*\*|__)(.+?)\1")


def plain(markdown: str) -> str:
    """Join writes Markdown; the text is read by people and by models, so only list markers and
    bold are tidied."""
    return _EMPHASIS.sub(r"\2", _BULLET.sub("- ", markdown)).strip()


async def company_id(http: Http, board: str) -> str:
    """The API takes the numeric company id; the career-page slug in the URL is looked up on the
    company page, which names it."""
    if board.isdigit():
        return board
    page = await get_page(http, f"https://join.com/companies/{board}")
    m = _COMPANY_ID.search(page.text)
    if not m:
        raise ValueError(f"join: no company id on the page of {board!r}")
    return m[1]


class Join(Source):
    """The board is the numeric company id, or the slug of `join.com/companies/<slug>`."""

    name = "join"
    kind = "ats"
    url_patterns = (re.compile(r"join\.com/companies/([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        cid = await company_id(http, task.board)
        page = start_page + 1
        while True:
            data = await http.get_json(
                f"{API}/companies/{cid}/jobs", params={"page": page, "pageSize": PAGE_SIZE}
            )
            items = [i for i in data.get("items") or [] if i.get("id")]
            stubs = await asyncio.gather(*(self.posting(http, i, task.board) for i in items))
            yield [s for s in stubs if s]
            if page >= (data.get("pagination") or {}).get("pageCount", 0):
                return
            page += 1

    @staticmethod
    async def detail(http: Http, job_id: int | str) -> dict[str, Any] | None:
        try:
            return await http.get_json(f"{API}/jobs/{job_id}")  # type: ignore[no-any-return]
        except GONE:  # one gone posting must not stop the board
            return None

    async def posting(self, http: Http, item: dict[str, Any], board: str) -> JobStub | None:
        detail = await self.detail(http, item["id"])
        domain = ((detail or {}).get("company") or {}).get("domain")
        if not detail or not domain or not item.get("title"):
            return None
        city = item.get("city") or {}
        location = ", ".join(x for x in (city.get("cityName"), city.get("countryName")) if x)
        url = f"https://join.com/companies/{domain}/{item.get('idParam') or item['id']}"
        return JobStub(
            source="join",
            url=url,
            title=" ".join(item["title"].split()),
            company=name_from_slug(domain),
            location=location,
            description=plain(detail.get("description") or ""),
            posted_at=from_iso(item.get("createdAt")),
            ats="join",
            apply_url=url,
            remote=mode(item.get("workplaceType")) or remote_from_text(location),
            extra={"board": board, "id": str(item["id"])},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        m = _JOB_URL.search(stub.url)
        detail = await self.detail(http, m[1]) if m and not stub.description else None
        text = plain((detail or {}).get("description") or "")
        return stub.model_copy(update={"description": text}) if text else stub
