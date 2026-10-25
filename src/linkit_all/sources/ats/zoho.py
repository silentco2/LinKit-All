"""Zoho Recruit career sites ({company}.zohorecruit.com, .eu, ...): the careers page embeds the
opening list as JSON in a hidden input, and each posting's page embeds its record as a JS-escaped
blob. Logic adapted from freehire (MIT)."""

import html
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, hydrate, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_host, when
from linkit_all.sources.text import html_to_text

CHUNK = 20  # postings per yielded page: their detail fetches run together
# The page escapes quotes as \x22, so the markers below are literal backslash-x-2-2.
_DESC = re.compile(r"\\x22Job_Description\\x22:\\x22(.*?)\\x22,\\x22[A-Za-z_]")
_OPENED = re.compile(r"\\x22Date_Opened\\x22:\\x22([0-9\\-]+)\\x22")
_ESCAPE = re.compile(r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)", re.S)
_SIMPLE = {"n": "\n", "t": "\t", "r": ""}


def _unescape_once(m: re.Match[str]) -> str:
    c = m[1]
    if len(c) > 1:  # \xNN or \uNNNN
        return chr(int(c[1:], 16))
    return _SIMPLE.get(c, c)  # \\ \/ \" \- and any stray \X give X, as JavaScript does


def js_unescape(s: str) -> str:
    """Decode the JS string escaping of an embedded value. A rich-text field is escaped twice, so
    one pass leaves stray backslashes before slashes and quotes: repeat until the text stops
    changing."""
    for _ in range(8):  # observed nesting is two levels; the cap is only a guard
        nxt = _ESCAPE.sub(_unescape_once, s)
        if nxt == s:
            break
        s = nxt
    return s


def detail_of(page: str) -> tuple[str, str] | None:
    """(description HTML, Date_Opened) from a posting page; None without a description."""
    m = _DESC.search(page)
    if m is None:
        return None
    opened = _OPENED.search(page)
    return html.unescape(js_unescape(m[1])), js_unescape(opened[1]) if opened else ""


class Zoho(Source):
    """The board is the careers host: `lithan.zohorecruit.com` (the TLD follows the data region)."""

    name = "zoho"
    kind = "ats"
    url_patterns = (
        re.compile(r"(?<![\w.-])((?!www\.)[\w-]+\.zohorecruit\.[a-z]+(?:\.[a-z]+)?)", re.I),
    )
    cdx_hosts = ("*.zohorecruit.com", "*.zohorecruit.eu")

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board.lower()
        listing = (await get_page(http, f"https://{host}/jobs/Careers")).text
        node = LexborHTMLParser(listing).css_first("input#jobs")  # the parser decodes &quot;
        raw = (node.attributes.get("value") if node else None) or ""
        if not raw:
            raise ValueError(f"zoho: no #jobs data on {host}")
        openings = [o for o in json.loads(raw) if o.get("Publish") and o.get("id")]

        async def build(o: dict[str, Any]) -> JobStub | None:
            url = f"https://{host}/jobs/Careers/{o['id']}"
            page = await page_text(http, url)
            found = detail_of(page) if page else None
            if found is None or not (body := html_to_text(found[0])):
                return None
            place = (o.get("City"), o.get("Country"))
            location = ", ".join(p for p in place if p)
            return JobStub(
                source=self.name,
                url=url,
                title=" ".join((o.get("Posting_Title") or "").split()),
                company=name_from_host(host),
                location=location,
                description=body,
                posted_at=when(found[1]),
                ats=self.name,
                apply_url=url,
                remote="remote" if o.get("Remote_Job") else remote_from_text(location),
                extra={"board": task.board, "id": str(o["id"])},
            )

        async for stubs in hydrate(openings, start_page, build, CHUNK):
            yield stubs
