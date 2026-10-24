"""Bullhorn staffing ATS career boards via the vendor's public REST API; the board is
"<cluster>:<corpToken>" (both are embedded in every Bullhorn career portal). Logic adapted from
freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task, from_epoch_ms
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

API = "https://public-rest{cls}.bullhornstaffing.com/rest-services/{token}"
PAGE_SIZE = 500
MAX_PAGES = 40  # 20k postings; a runaway guard
# A bare "address" returns an empty object: its sub-fields have to be asked for.
FIELDS = "id,title,publicDescription,address(city,state,countryName),dateAdded,employmentType"


def split_board(board: str) -> tuple[str, str]:
    """ "cls:token" (shorthand) or "cls/token" (what the URL detector produces)."""
    parts = re.split(r"[:/]", board, maxsplit=1)
    if len(parts) != 2 or not all(parts):
        raise ValueError(f"bullhorn board {board!r} must be <cluster>:<corpToken>")
    return parts[0], parts[1]


class Bullhorn(Source):
    name = "bullhorn"
    kind = "ats"
    url_patterns = (
        re.compile(r"public-rest(\d+)\.bullhornstaffing\.com/rest-services/(\w+)", re.I),
    )
    parallel = 2  # public JSON API; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        cls, token = split_board(task.board)

        async def fetch(start: int) -> tuple[list[dict[str, Any]], int | None]:
            data = await http.get_json(
                API.format(cls=cls, token=token) + "/search/JobOrder",
                params={"query": "(isOpen:1)", "fields": FIELDS, "sort": "-dateAdded",
                        "count": PAGE_SIZE, "start": start},
            )  # fmt: skip
            return data.get("data") or [], data.get("total")

        async for items in paged(fetch, PAGE_SIZE, start_page, max_pages=MAX_PAGES):
            yield [self.stub(o, cls, token) for o in items if o.get("id")]

    @staticmethod
    def stub(o: dict[str, Any], cls: str, token: str) -> JobStub:
        # The API has no human-facing job page: the REST entity reference identifies the posting.
        url = API.format(cls=cls, token=token) + f"/entity/JobOrder/{o['id']}"
        addr = o.get("address") or {}
        city_state = [str(addr[k]).strip() for k in ("city", "state") if addr.get(k)]
        location = ", ".join(city_state) or (addr.get("countryName") or "").strip()
        return JobStub(
            source="bullhorn",
            url=url,
            title=(o.get("title") or "").strip(),
            company=token,  # the API names no agency
            location=location,
            description=html_to_text(o.get("publicDescription") or ""),
            posted_at=from_epoch_ms(o.get("dateAdded")),
            ats="bullhorn",
            apply_url=url,
            extra={
                "board": f"{cls}:{token}",
                "id": str(o["id"]),
                "employment": o.get("employmentType"),
            },
        )
