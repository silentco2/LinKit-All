"""Pandape (pandape.com.br), the ATS InfoJobs Brasil sells to employers: <tenant>.pandape.infojobs.
com.br lists vacancies through a POST that answers rendered cards, and each vacancy page carries a
JobPosting block. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f12 import name_from_slug
from linkit_all.sources.ats._f16 import page_text, when
from linkit_all.sources.ats._f17 import XHR, hydrate, post_form, text_of
from linkit_all.sources.base import JobStub, Remote, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import html_to_text

HOST = "{board}.pandape.infojobs.com.br"
PAGE = 20  # vacancies per listing page
MAX_PAGES = 1000
CHUNK = 20  # vacancy pages fetched together per page of stubs
_BOARD = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_DETAIL = re.compile(r"^/Detail/(\d+)$")
_MODES: dict[str, Remote] = {"Home Office": "remote", "Híbrido": "hybrid", "Presencial": "onsite"}
_BRT = timedelta(hours=3)  # the site writes Brasília time without an offset


@dataclass(frozen=True)
class Card:
    id: str
    title: str
    location: str
    work_mode: str
    contract: str


def parse_cards(fragment: str) -> list[Card]:
    """The vacancy cards of one listing page: title, and the place, work mode and contract the
    card names next to icons."""
    cards = []
    for a in LexborHTMLParser(fragment).css("a.card-vacancy"):
        m = _DETAIL.match(a.attributes.get("href") or "")
        title = text_of(a.css_first("h3"))
        if not m or not title:
            continue
        facts = {"location": "", "mode": "", "contract": ""}
        for icon in a.css("i.icon"):
            holder = icon.parent.parent if icon.parent is not None else None
            classes = (icon.attributes.get("class") or "").split()
            if "icon-location-pin-1" in classes:
                facts["location"] = text_of(holder)
            elif {"icon-buildings", "icon-building-house", "icon-user-with-headphones"} & set(
                classes
            ):
                facts["mode"] = text_of(holder)
            elif "icon-sheet" in classes:
                facts["contract"] = text_of(holder)
        cards.append(Card(m[1], title, facts["location"], facts["mode"], facts["contract"]))
    return cards


def _posted(value: str | None) -> datetime | None:
    m = re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d", value or "")
    return when((datetime.fromisoformat(m[0]) + _BRT).isoformat()) if m else None


def parse_vacancy(html: str, card: Card, url: str, board: str) -> JobStub | None:
    """The card joined with its page: the page body plus the requirements and valued sections,
    else the JobPosting's plain description."""
    found = job_postings(html)
    if not found:
        return None
    posting, tree = found[0], LexborHTMLParser(html)
    stub = to_stub({**posting, "datePosted": None}, "pandape", url, "pandape")
    body = tree.css_first("#description .order-1")
    parts = [html_to_text(body.html or "")] if body else []
    if not any(parts):
        parts = [str(posting.get("description") or "").strip()]
    for ident in ("Requirements", "Valued"):
        if section := tree.css_first(f"#{ident}"):
            parts.append(html_to_text(section.html or ""))
    address = (posting.get("jobLocation") or {}).get("address") or {}
    if isinstance(address, dict) and address.get("addressLocality"):
        place = [address["addressLocality"], address.get("addressRegion")]
        location = ", ".join(str(p) for p in place if p)
    else:
        location = card.location
    return stub.model_copy(
        update={
            "title": card.title,
            "company": stub.company if stub.company != "Unknown" else name_from_slug(board),
            "location": location,
            "description": "\n\n".join(p for p in parts if p),
            "posted_at": _posted(posting.get("datePosted")),
            "remote": _MODES.get(card.work_mode) or remote_from_text(location),
            "extra": {**stub.extra, "board": board, "id": card.id, "contract": card.contract},
        }
    )


class Pandape(Source):
    """The board is the tenant label: `braspress` for braspress.pandape.infojobs.com.br."""

    name = "pandape"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w-])([\w-]+)\.pandape\.infojobs\.com\.br", re.I),)
    cdx_hosts = ("*.pandape.infojobs.com.br",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.strip().lower()
        if not _BOARD.match(board):
            raise ValueError(f"pandape: board {task.board!r} is not a tenant label")
        site = "https://" + HOST.format(board=board)
        await http.allowed(f"{site}/ListVacancies")
        cards = await self.cards(http, site, board)
        read = 0

        async def build(card: Card) -> JobStub | None:
            nonlocal read
            url = f"{site}/Detail/{card.id}"
            html = await page_text(http, url)
            stub = parse_vacancy(html, card, url, board) if html else None
            read += stub is not None
            return stub

        async for page in hydrate(cards, start_page, build, CHUNK):
            yield page
        if cards and start_page == 0 and not read:
            raise ValueError(f"pandape: listed {len(cards)} vacancies and read none of their pages")

    @staticmethod
    async def cards(http: Http, site: str, board: str) -> list[Card]:
        """Every card, walked page by page until the site says `isLast`; a walk that ends short of
        the stated total is an error, not a partial board."""
        cards: dict[str, Card] = {}
        total = -1
        for number in range(1, MAX_PAGES + 1):
            form = {"PageNumber": number, "PageSize": PAGE}
            try:
                resp = await post_form(http, f"{site}/ListVacancies", form, XHR)
            except httpx.HTTPStatusError as e:
                if number == 1 and e.response.status_code == 404:
                    raise ValueError(f"pandape: board {board!r} does not exist") from e
                raise
            data = resp.json()
            if "isLast" not in data or "subtotal" not in data:
                raise ValueError(f"pandape: page {number} carries no isLast/subtotal")
            total = data["subtotal"] if total < 0 else total
            got = parse_cards(data.get("view") or "")
            cards.update({c.id: c for c in got if c.id not in cards})
            if data["isLast"]:
                if len(cards) < total:
                    raise ValueError(
                        f"pandape: read {len(cards)} vacancies, the site states {total}"
                    )
                return list(cards.values())
            if not got:
                raise ValueError(f"pandape: page {number} is empty before the last page")
        raise ValueError(f"pandape: no end of the listing after {MAX_PAGES} pages")
