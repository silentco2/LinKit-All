"""UKG Pro Recruiting career sites (formerly UltiPro): a keyless POST JSON search plus a detail page
that bootstraps the full posting as a JSON literal. Logic adapted from freehire (MIT)."""

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import page_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import bracket_slice, name_from_slug
from linkit_all.sources.text import html_to_text

PAGE = 50
LIST = "https://{host}/{tenant}/JobBoard/{guid}/JobBoardView/LoadSearchResults"
DETAIL = "https://{host}/{tenant}/JobBoard/{guid}/OpportunityDetail?opportunityId={id}"
_MARKER = "CandidateOpportunityDetail("  # the call whose JSON argument is the opportunity
_GUID = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"


def split_board(board: str) -> tuple[str, str, str]:
    """ "host/tenant/guid" -> its three parts; the host carries the data-residency TLD."""
    parts = board.strip("/").split("/")
    if len(parts) != 3 or not all(parts):
        raise ValueError(f"ukg: board {board!r} must be <host>/<tenant>/<guid>")
    return parts[0], parts[1], parts[2]


def location_of(o: dict[str, Any]) -> str:
    """The first location as "City, State, Country"; its label when it has no address."""
    loc = (o.get("Locations") or [{}])[0]
    addr = loc.get("Address") or {}
    parts = (
        addr.get("City"),
        (addr.get("State") or {}).get("Name"),
        (addr.get("Country") or {}).get("Name"),
    )
    return ", ".join(p for p in parts if p) or loc.get("LocalizedName") or ""


def detail_of(page: str) -> dict[str, Any] | None:
    """The opportunity the detail page bootstraps in an inline script, or None."""
    for script in LexborHTMLParser(page).css("script"):
        text = script.text(deep=True)
        if _MARKER in text and (raw := bracket_slice(text, _MARKER, "{", "}")):
            try:
                data = json.loads(raw)
            except ValueError:
                return None
            return data if isinstance(data, dict) and data.get("Description") else None
    return None


class UKG(Source):
    """The board is `<host>/<tenant>/<guid>`: the JobBoard URL without its scheme and path."""

    name = "ukg"
    kind = "ats"
    url_patterns = (
        re.compile(rf"([\w.-]*(?:ultipro\.[a-z]+|ukg\.net))/([\w]+)/JobBoard/({_GUID})", re.I),
    )
    cdx_hosts = ("recruiting.ultipro.com/*", "recruiting.ultipro.ca/*", "rec.pro.ukg.net/*")
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host, tenant, guid = split_board(task.board)
        url = LIST.format(host=host, tenant=tenant, guid=guid)
        skip = start_page * PAGE
        while True:
            body = {"opportunitySearch": {"Top": PAGE, "Skip": skip}}
            data = await http.post_json(url, body)
            opps = [o for o in data.get("opportunities") or [] if o.get("Id")]
            if not opps:
                return
            # The list carries a brief description only; each detail page upgrades it.
            yield list(await asyncio.gather(*(self.stub(http, o, task.board) for o in opps)))
            skip += len(opps)
            if skip >= (data.get("totalCount") or 0):
                return

    async def stub(self, http: Http, o: dict[str, Any], board: str) -> JobStub:
        host, tenant, guid = split_board(board)
        url = DETAIL.format(host=host, tenant=tenant, guid=guid, id=o["Id"])
        body, employment = o.get("BriefDescription") or "", None
        page = await page_text(http, url)  # a missing detail keeps the brief body
        if page and (detail := detail_of(page)):
            body = detail["Description"]
            full = detail.get("FullTime")
            employment = None if full is None else ("full_time" if full else "part_time")
        location = location_of(o)
        return JobStub(
            source=self.name,
            url=url,
            title=" ".join((o.get("Title") or "").split()),
            company=name_from_slug(tenant),
            location=location,
            description=html_to_text(body, escaped=True),
            posted_at=from_iso(o.get("PostedDate")),
            ats=self.name,
            apply_url=url,
            remote=remote_from_text(location),
            extra={"board": board, "id": o["Id"], "employment": employment},
        )
