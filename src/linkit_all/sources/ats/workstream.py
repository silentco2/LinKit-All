"""Workstream (www.workstream.us), the hourly-hiring ATS of restaurants, retail and care homes: the
employer-wide positions listing is server-rendered cards and each posting page carries the body.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.sources.ats._f13 import get_page, name_from_slug
from linkit_all.sources.ats._f16 import GONE, chunks
from linkit_all.sources.ats._f17 import text_of
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

BASE = "https://www.workstream.us"
CHUNK = 10  # postings per yielded page (also the listing's cards per page)
MAX_PAGES = 200  # backstop for a page that states no page count
_POSTING = re.compile(r"^/j/[0-9a-f]{8}/[^/]+/[^/]+/[^/]+-([0-9a-f]{8})$")  # ends in the posting id
_SEARCH_BASE = re.compile(r"var searchBaseUrl = '([^']+)'")
_TOTAL_PAGES = re.compile(r"var totalPages = (\d+)")
_TITLE = re.compile(r"\s*(?:Careers and Jobs|Careers|Jobs)\s*$", re.I)


@dataclass
class Card:
    id: str
    url: str
    title: str
    location: str
    employment: str | None
    pay: str


def posting_id(href: str) -> str:
    """The id a posting path ends with ("" for brand, store, apply and listing paths)."""
    m = _POSTING.match(urlsplit(href).path)
    return m[1] if m else ""


def cards_of(page: str) -> list[Card]:
    """The positions listing's cards in page order, minus any that link no posting."""
    cards = []
    for node in LexborHTMLParser(page).css(".position-card"):
        link = next(
            (a for a in node.css("a[href]") if posting_id(a.attributes.get("href") or "")), None
        )
        if link is None:
            continue
        href = link.attributes["href"] or ""
        tags = [text_of(t) for t in node.css(".tag")]
        icon = node.css_first('img[data-icon="rate-of-pay"]')
        cards.append(
            Card(
                id=posting_id(href),
                url=urljoin(BASE, urlsplit(href).path),  # without the "?locale=en" every link has
                title=text_of(link),
                location=text_of(node.css_first(".position-address")),
                # Several schedules at once ("Full-time" and "Part-time") state no single type.
                employment=tags[0] if len(tags) == 1 else None,
                pay=text_of(icon.parent) if icon is not None else "",
            )
        )
    return cards


def page_url(base: str, page: int) -> str:
    parts = urlsplit(base)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "page"] + [("page", str(page))]
    return urlunsplit(parts._replace(query=urlencode(query)))


def body_of(page: str) -> str:
    node: LexborNode | None = LexborHTMLParser(page).css_first(".position-rich-text-content")
    return html_to_text(node.html or "") if node else ""


async def fetch(http: Http, url: str) -> str:
    return (await get_page(http, url)).text


class Workstream(Source):
    """The board is the employer's eight hex characters from `www.workstream.us/j/<board>`; one
    board is one employer account, whatever brands it trades under."""

    name = "workstream"
    kind = "ats"
    url_patterns = (re.compile(r"workstream\.us/j/([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        cards, company = await self.listing(http, task.board)

        async def build(card: Card) -> JobStub | None:
            try:
                body = body_of(await fetch(http, card.url))
            except GONE:
                return None
            # Not stored body-less: the next run retries the posting.
            return self.stub(card, body, task.board, company) if body else None

        for chunk in chunks(cards, start_page, CHUNK):
            yield [s for card in chunk if (s := await build(card))]

    @staticmethod
    async def listing(http: Http, board: str) -> tuple[list[Card], str]:
        """Every card of the employer's positions listing, and the employer's name. The page
        states where its positions listing lives: for a multi-brand employer that is the URL
        asked for, for a single-brand one the brand's own, reached by one more request."""
        asked = f"{BASE}/j/{board}/positions"
        page = await fetch(http, asked)
        stated = _SEARCH_BASE.search(page)
        if stated is None:
            raise ValueError(f"workstream: no positions listing on the {board} page")
        base = urljoin(BASE, stated[1])
        if base != asked:
            page = await fetch(http, base)
        title = LexborHTMLParser(page).css_first("title")
        name = _TITLE.sub("", text_of(title)) if title else ""
        total = _TOTAL_PAGES.search(page)
        pages = int(total[1]) if total and 1 <= int(total[1]) <= MAX_PAGES else MAX_PAGES
        found: dict[str, Card] = {}
        for n in range(1, pages + 1):
            if n > 1:
                page = await fetch(http, page_url(base, n))
            new = cards_of(page)
            if not new:  # an empty page ends the listing
                break
            for card in new:
                found.setdefault(card.id, card)
        return list(found.values()), name or name_from_slug(board)

    @staticmethod
    def stub(card: Card, body: str, board: str, company: str) -> JobStub:
        # The pay line is quoted, never parsed into the salary fields: its "$" is unqualified
        # and the platform serves Canadian employers too.
        pay = f"\n\nPay: {card.pay}" if card.pay else ""
        return JobStub(
            source="workstream",
            url=card.url,
            title=card.title,
            company=company,
            location=card.location,
            description=body + pay,
            ats="workstream",
            apply_url=card.url,
            remote=remote_from_text(card.location),
            extra={"board": board, "id": card.id, "employment": card.employment},
        )
