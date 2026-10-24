"""Oracle Taleo Enterprise career sites (board = "host/careersection", e.g. "valero.taleo.net/2"):
the careersection page sets an anonymous session and names its portal, the searchjobs call pages
the requisitions and each requisition's page holds the description. Logic adapted from freehire
(MIT)."""

import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx
from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f13 import name_from_host
from linkit_all.sources.ats._f15 import get_page
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

_PORTAL = re.compile(r"portalNo:\s*'(\d+)'")  # authorizes the searchjobs call
_PCT = re.compile(rb"%([0-9A-Fa-f]{2})")
_HEADERS = {"tz": "GMT+00:00", "tzname": "UTC"}
_MAX_PAGES = 200


def _body(page: int) -> dict[str, Any]:
    """The unfiltered search, newest first, at the given 1-based page."""
    empty: dict[str, Any] = {"searchFilterSelections": []}
    return {
        "multilineEnabled": False,
        "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": False},
        "fieldData": {},
        "filterSelectionParam": empty,
        "advancedSearchFiltersSelectionParam": empty,
        "pageNo": page,
    }


def _unescape(text: str) -> str:
    """Percent-decode, leaving a stray "%" (Word-pasted CSS: "115%") and "+" as they are."""
    raw = _PCT.sub(lambda m: bytes([int(m[1], 16)]), text.encode())
    return raw.decode("utf-8", "replace")


def description(page: str) -> str:
    """The description of a jobdetail.ftl page: the hidden `initialHistory` field is "!|!"-split
    state and the percent-encoded description HTML follows its "!*!" marker."""
    node = LexborHTMLParser(page).css_first('input[name="initialHistory"]')
    _, found, after = (
        (node.attributes.get("value") or "").partition("!*!") if node else ("", "", "")
    )
    return html_to_text(_unescape(after.split("!|!")[0])) if found else ""


def _place(cell: str) -> str:
    """A location cell is a JSON array of places, or plain text."""
    try:
        places = json.loads(cell)
    except ValueError:
        return cell.strip()
    return (
        ", ".join(str(p).strip() for p in places if str(p).strip())
        if isinstance(places, list)
        else cell.strip()
    )


def _posted(cells: list[str]) -> datetime | None:
    """The first cell in Taleo's "Jul 2, 2026" listing format; tenants may list no date."""
    for cell in cells:
        try:
            return datetime.strptime(cell.strip(), "%b %d, %Y")
        except ValueError:
            continue
    return None


class Taleo(Source):
    name = "taleo"
    kind = "ats"
    url_patterns = (re.compile(r"([\w.-]+\.taleo\.net)/careersection/(?!rest\b)([\w-]+)", re.I),)
    cdx_hosts = ("*.taleo.net/careersection/*",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host, _, section = task.board.partition("/")
        if not host or not section:
            raise Unsupported(f'taleo: board "{task.board}" must be "host/section"')
        page_url = f"https://{host}/careersection/{section}/jobsearch.ftl?lang=en"
        portal = _PORTAL.search((await get_page(http, page_url)).text)
        if portal is None:
            raise Unsupported(
                f"taleo: no portal number on {host}/{section} (not a public section?)"
            )
        api = f"https://{host}/careersection/rest/jobboard/searchjobs?lang=en&portal={portal[1]}"
        size = 0
        for page in range(start_page + 1, _MAX_PAGES + 1):
            data = await http.post_json(api, _body(page), headers=_HEADERS)
            rows = data.get("requisitionList") or []
            yield [s for r in rows if (s := self._stub(r, host, section, task.board))]
            size = size or len(rows)
            total = (data.get("pagingData") or {}).get("totalCount") or 0
            if not rows or (total > 0 and page * size >= total):  # <= 0 is no proof of the end
                return

    def _stub(self, row: dict[str, Any], host: str, section: str, board: str) -> JobStub | None:
        cells = [str(c) for c in row.get("column") or []]
        number = str(row.get("contestNo") or "").strip()
        title = " ".join(cells[0].split()) if cells else ""
        if not (number and title):
            return None
        # the cell order is the tenant's own; the API names which cells hold the location
        cols = [i for i in row.get("locationsColumns") or [] if 0 <= i < len(cells)]
        location = ", ".join(p for p in (_place(cells[i]) for i in cols) if p)
        url = f"https://{host}/careersection/{section}/jobdetail.ftl?job={number}&lang=en"
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=name_from_host(host),
            location=location,
            posted_at=_posted(cells),
            ats=self.name,
            apply_url=url,
            remote=remote_from_text(location),
            extra={"board": board, "id": number},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        """The list has no description; a requisition page that is gone leaves the stub as is."""
        try:
            text = (await get_page(http, stub.url)).text
        except httpx.HTTPStatusError:
            return stub
        return stub.model_copy(update={"description": description(text)})
