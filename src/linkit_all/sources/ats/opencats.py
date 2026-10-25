"""Self-hosted OpenCATS career portals: the show-all listing links every posting and each showJob
page carries labelled fields and the body. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, hydrate, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_host, next_element, node_text
from linkit_all.sources.text import html_to_text

CHUNK = 20  # posting pages fetched together per page of stubs
LISTING = "index.php?m=careers&p=showAll"
_ID = re.compile(r"[?&]ID=(\d+)")
_CLICK = re.compile(r"""location\.href\s*=\s*['"]([^'"]+)['"]""")
# Where installs put the posting body (id or class); the shipped template says "descriptive" and
# one install ships a typo. A closed list on purpose: an unknown container gives no description,
# which is visible, where a guess would store page chrome as the job text.
_BODY = ("descriptive", "job-description", "job-decription", "description")
# Standing talent-pool forms parked in the portal beside the real openings.
_GENERAL = ("apply here", "general application", "open application", "spontaneous application")


@dataclass(frozen=True)
class Listed:
    url: str
    id: str
    title: str


def listed(html: str, base: str) -> list[Listed]:
    """Postings of a listing page by the one thing a re-skinned template cannot change: the
    showJob route, carried by an anchor (its text is the title) or a clickable row (the title is
    the row's first cell). The first carrier of an id wins; it is the title link."""
    found: dict[str, Listed] = {}
    for node in LexborHTMLParser(html).css("a[href], [onclick]"):
        if node.tag == "a":
            loc, title = node.attributes.get("href") or "", node_text(node)
        else:
            m = _CLICK.search(node.attributes.get("onclick") or "")
            first = next((c for c in node.iter() if c.tag != "-text"), None)
            loc, title = (m[1] if m else ""), node_text(first)
        ident = _ID.search(loc)
        if "p=showJob" not in loc or not ident or ident[1] in found:
            continue
        if any(g in title.lower() for g in _GENERAL):
            continue
        found[ident[1]] = Listed(urljoin(base, loc), ident[1], title)
    return list(found.values())


def _label_value(tree: LexborHTMLParser, label: str) -> str:
    for cell in tree.css("td, th"):
        raw = cell.text(deep=True)
        if label in raw.lower() and len(raw) < 60:  # a label cell, not a wrapper around the table
            value = next_element(cell)
            if value is not None and (text := node_text(value)):
                return text
    return ""


def location_of(tree: LexborHTMLParser) -> str:
    """The labelled Location field; failing that the first row of the details table, since an
    install in another language translates the label but not the template's row order."""
    if found := _label_value(tree, "location"):
        return found
    row = tree.css_first("#detailsTable tr")
    first = next((c for c in row.iter() if c.tag != "-text"), None) if row else None
    return node_text(next_element(first)) if first is not None else ""


def body_of(tree: LexborHTMLParser) -> str:
    for name in _BODY:
        node = tree.css_first(f'[id="{name}"]') or tree.css_first(f".{name}")
        if node is not None:
            return html_to_text(node.html or "")
    return ""


class OpenCats(Source):
    """The board is the portal root: the host, plus the path it is mounted under when it is not
    the web root (`careers.example.pt/careers`). Self-hosted, so no URL pattern."""

    name = "opencats"
    kind = "ats"

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = re.sub(r"^https?://", "", task.board.strip()).strip("/")
        if "." not in board.split("/")[0] or re.search(r"[:?#@\s]", board):
            raise ValueError(f"opencats: board {task.board!r} is not a portal root")
        base = f"https://{board}/"
        page = await get_page(http, base + LISTING)
        company = name_from_host(board.split("/")[0])

        async def build(item: Listed) -> JobStub | None:
            return await self.posting(http, item, board, company)

        async for stubs in hydrate(listed(page.text, base), start_page, build, CHUNK):
            yield stubs

    async def posting(self, http: Http, item: Listed, board: str, company: str) -> JobStub | None:
        html = await page_text(http, item.url)
        if html is None:
            return None
        tree = LexborHTMLParser(html)
        location = location_of(tree)
        return JobStub(
            source="opencats",
            url=item.url,
            title=item.title,
            company=company,
            location=location,
            description=body_of(tree),
            ats="opencats",
            apply_url=item.url,
            remote=remote_from_text(location),
            extra={"board": board, "id": item.id},
        )
