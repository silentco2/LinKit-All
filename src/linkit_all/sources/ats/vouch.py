"""vouch.careers, a referral-driven careers platform: the company page is a Next.js app that inlines
every posting, fully populated, in its RSC "flight" stream. Logic adapted from freehire (MIT)."""

import html
import json
import re
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urljoin

from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import bracket_slice, decode_flight, mode
from linkit_all.sources.text import html_to_text

BASE = "https://vouch.careers"


def work_mode(types: list[str]) -> Remote | None:
    """employmentType mixes contract words ("Full-time") with workplace ones; when a posting lists
    several workplaces the most permissive wins: remote, then hybrid, then on-site."""
    found = {mode(t) for t in types}
    order: tuple[Remote, ...] = ("remote", "hybrid", "onsite")
    return next((m for m in order if m in found), None)


def location_of(listing: dict[str, Any]) -> str:
    """The first location's address, else its city / area / country (remote roles have none)."""
    loc = (listing.get("locations") or [{}])[0]
    parts = (loc.get("city"), loc.get("administrative_area"), loc.get("country"))
    return loc.get("address") or ", ".join(p for p in parts if p)


class Vouch(Source):
    """The board is the company's id in `vouch.careers/companies/<id>`."""

    name = "vouch"
    kind = "ats"
    url_patterns = (re.compile(r"vouch\.careers/companies/([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one page holds every posting
            return
        page = (await get_page(http, f"{BASE}/companies/{task.board}")).text
        try:
            flight = decode_flight(page)
        except ValueError as e:
            raise ValueError(f"vouch: no Next.js payload on the {task.board} page") from e
        raw = bracket_slice(flight, '"listings":', "[", "]")
        if raw is None:
            raise ValueError(f"vouch: no listings in the {task.board} page (markup changed?)")
        # Not live (deactivated, draft or unlisted) is not a vacancy; an id-less one has no key.
        live = (
            lst
            for lst in json.loads(raw)
            if lst.get("id")
            and lst.get("activated")
            and not lst.get("draft")
            and not lst.get("unlisted")
        )
        yield [self.stub(lst, task.board) for lst in live]

    @staticmethod
    def stub(lst: dict[str, Any], board: str) -> JobStub:
        url = urljoin(BASE, lst.get("url") or f"/companies/{board}/{lst['id']}")
        location = location_of(lst)
        # The pitch is plain prose: escape it, or a bare "<" would swallow the rest as a tag.
        pitch = f"<p>{html.escape(lst['pitch'])}</p>" if lst.get("pitch") else ""
        body = pitch + "".join(lst.get(k) or "" for k in ("description", "must", "nice"))
        return JobStub(
            source="vouch",
            url=url,
            title=" ".join((lst.get("title") or "").split()),
            company=(lst.get("company") or {}).get("name") or "Unknown",
            location=location,
            description=html_to_text(body),
            posted_at=from_iso(lst.get("publishedAt")),
            ats="vouch",
            apply_url=url,
            remote=work_mode(lst.get("employmentType") or []) or remote_from_text(location),
            extra={"board": board, "id": lst["id"]},
        )
