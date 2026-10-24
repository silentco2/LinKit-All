"""Paycor Recruiting career sites (recruitingbypaycor.com/career/CareerHome.action?clientId=...):
a server-rendered listing and a JobIntroduction page per posting. Logic adapted from freehire
(MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import parse_qs, urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.sources.ats._f12 import get_page
from linkit_all.sources.ats._f16 import page_text
from linkit_all.sources.ats._f17 import hydrate
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

BASE = "https://recruitingbypaycor.com/career"
ACTION = "JobIntroduction.action"
CHUNK = 20  # posting pages fetched together per page of stubs


def posting_id(href: str, board: str) -> str:
    """The posting id of a JobIntroduction link on this board; "" for the board's id-less "submit
    your resume" link and for postings of another client (an employer's themed listing shows
    both)."""
    parts = urlsplit(href)
    if not parts.path.endswith("/" + ACTION):
        return ""
    query = parse_qs(parts.query)
    if (query.get("clientId") or [""])[0].lower() != board.lower():
        return ""
    return (query.get("id") or [""])[0]


def field(tree: LexborHTMLParser, ident: str) -> str:
    """The value of a labelled cell: its text without the leading bold "Position:" label."""
    cell = tree.css_first(f"#{ident}")
    if cell is None:
        return ""
    parts: list[str] = []
    for i, child in enumerate(c for c in cell.iter(include_text=True) if _text(c)):
        if i == 0 and child.tag == "b" and _text(child).endswith(":"):
            continue
        parts.append(_text(child))
    return " ".join(parts)


def _text(node: LexborNode) -> str:
    return " ".join(node.text(deep=True).split())


def parse_posting(html: str, board: str, ident: str, url: str) -> JobStub | None:
    tree = LexborHTMLParser(html)
    title = field(tree, "gnewtonJobPosition")
    if not title:  # a filled or never-existing posting answers 200 with a notice in place of cells
        return None
    location = field(tree, "gnewtonJobLocationInfo")
    body = tree.css_first("#gnewtonJobDescriptionText")
    return JobStub(
        source="paycor",
        url=url,
        title=title,
        company=f"Paycor {board}",  # the pages name no employer
        location=location,
        description=html_to_text(body.html or "") if body else "",
        ats="paycor",
        apply_url=url,
        remote=remote_from_text(location),
        extra={"board": board, "id": ident},
    )


class Paycor(Source):
    """The board is the client id: the hex string after clientId= in the careers URL."""

    name = "paycor"
    kind = "ats"
    url_patterns = (re.compile(r"recruitingbypaycor\.com/career/[^\s\"'#]*?clientId=(\w+)", re.I),)
    cdx_hosts = ("recruitingbypaycor.com/career/*",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.strip()
        if not re.fullmatch(r"\w+", board):
            raise ValueError(f"paycor: board {task.board!r} is not a client id")
        listing = f"{BASE}/CareerHome.action?clientId={board}"
        tree = LexborHTMLParser((await get_page(http, listing)).text)
        ids: dict[str, None] = {}
        for a in tree.css("a[href]"):
            if ident := posting_id(urljoin(listing, a.attributes.get("href") or ""), board):
                ids[ident] = None

        async def build(ident: str) -> JobStub | None:
            url = f"{BASE}/{ACTION}?clientId={board}&id={ident}"
            html = await page_text(http, url)
            return parse_posting(html, board, ident, url) if html else None

        async for stubs in hydrate(list(ids), start_page, build, CHUNK):
            yield stubs
