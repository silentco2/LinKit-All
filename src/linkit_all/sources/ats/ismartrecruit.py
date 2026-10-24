"""iSmartRecruit career boards (app.ismartrecruit.com/openJobWebsite?tenantId=...): the grid page
server-renders every open posting, a detail page holds the body in its og:description. Logic
adapted from freehire (MIT)."""

import base64
import binascii
import re
from collections.abc import AsyncIterator
from urllib.parse import unquote

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f13 import get_page, name_from_host
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

LIST = "https://app.ismartrecruit.com/openJobWebsite?tenantId={tenant}&view=grid&col=2&lang=en"
# A tenant or posting token is "E7p" + base64 + "Q9e": a fixed decorative envelope, not encryption.
_PREFIX, _SUFFIX = "E7p", "Q9e"
_X = re.compile(r"[?&]x=([^&]+)")
_POSTING = re.compile(r"_(\d+)_W_")  # the payload is "<domain>_<id>_W_<lang>"


def unwrap(token: str) -> str:
    """The text inside a token's envelope, base64-decoded; "" when it is not one."""
    token = unquote(token)
    if not (token.startswith(_PREFIX) and token.endswith(_SUFFIX)):
        return ""
    mid = token[len(_PREFIX) : -len(_SUFFIX)]
    for alt in (None, b"-_"):
        try:
            text = base64.b64decode(mid + "=" * (-len(mid) % 4), alt, validate=True).decode()
        except (binascii.Error, UnicodeDecodeError):
            continue
        if text.isprintable():
            return text
    return ""


def posting_id(href: str) -> str:
    m = _X.search(href)
    p = _POSTING.search(unwrap(m[1])) if m else None
    return p[1] if p else ""


def readable_board(board: str) -> str:
    """The `<domain>_<code>` tenant text, from itself or from the base64 a pasted URL carries."""
    try:
        decoded = base64.b64decode(board + "=" * (-len(board) % 4), validate=True).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return board
    return decoded if "_" in decoded and decoded.isprintable() else board


class ISmartRecruit(Source):
    """The board is the readable tenant text (`acme.com_1234`); the base64 form from a pasted
    widget URL works too."""

    name = "ismartrecruit"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"ismartrecruit\.com/openJobWebsite\?[^\s\"']*?tenantId=E7p([\w+/-]+?)Q9e", re.I
        ),
    )

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the grid holds every posting, unpaged
            return
        board = readable_board(task.board)
        tenant = _PREFIX + base64.b64encode(board.encode()).decode().rstrip("=") + _SUFFIX
        tree = LexborHTMLParser((await get_page(http, LIST.format(tenant=tenant))).text)
        company = name_from_host(board.rsplit("_", 1)[0])
        stubs: dict[str, JobStub] = {}
        for a in tree.css("a.jobListing_Data"):
            href = a.attributes.get("href") or ""
            job_id = posting_id(href)
            if not job_id or job_id in stubs:
                continue
            title, where = a.css_first(".ui-panel-title"), a.css_first(".ui-panelgrid-cell")
            location = " ".join(where.text().split()) if where else ""
            stubs[job_id] = JobStub(
                source=self.name,
                url=href,
                title=" ".join(title.text().split()) if title else "",
                company=company,
                location=location,
                ats=self.name,
                apply_url=href,
                remote=remote_from_text(location),
                extra={"board": board, "id": job_id},
            )
        yield list(stubs.values())

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if stub.description:
            return stub
        tree = LexborHTMLParser((await get_page(http, stub.url)).text)

        def og(prop: str) -> str:
            node = tree.css_first(f'meta[property="og:{prop}"]')
            return (node.attributes.get("content") or "").strip() if node else ""

        return stub.model_copy(
            update={
                "title": stub.title or og("title"),
                "description": html_to_text(og("description")),
            }
        )
