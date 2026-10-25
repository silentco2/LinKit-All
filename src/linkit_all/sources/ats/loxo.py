"""Loxo recruiting-agency career boards: a server-rendered listing links every /job/<token>, each
detail page holds the title and location in its meta tags and the HTML body in an embedded JSON
block. Logic adapted from freehire (MIT)."""

import asyncio
import base64
import binascii
import json
import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import chunks, get_page, page_text, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import links, name_from_slug

_TOKEN = re.compile(r"/job/([A-Za-z0-9=_-]+)(?:$|[/?#])")


def job_id(url: str) -> str:
    """Loxo's own `<agency id>-<slug>`, which the /job/<token> path carries in base64; the raw
    token when it does not decode to that; "" when the URL is not a posting."""
    m = _TOKEN.search(url)
    if not m:
        return ""
    token = m[1]
    for decode in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            text = decode(token + "=" * (-len(token) % 4)).decode("utf-8")
        except (binascii.Error, ValueError):
            continue
        if "-" in text and text.isprintable():
            return text
    return token


def _meta(tree: LexborHTMLParser, prop: str) -> str:
    node = tree.css_first(f'meta[property="{prop}"]')
    return " ".join((node.attributes.get("content") or "").split()) if node else ""


def _body(tree: LexborHTMLParser) -> str:
    """The HTML description from the first embedded application/json block that has one."""
    for node in tree.css('script[type="application/json"]'):
        try:
            data = json.loads(node.text(deep=True))
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("description"):
            return str(data["description"])
    return ""


def _location(og_description: str) -> str:
    """The og:description reads "<role>Location: <place>Salary: <pay>..."; no run, no location."""
    _, found, rest = og_description.partition("Location:")
    return rest.split("Salary:")[0].strip() if found else ""


class Loxo(Source):
    """The board is `<host>/<slug>`: an agency subdomain (`fitnext.app.loxo.co/fitnext`), the
    shared `app.loxo.co/<slug>` or a regional pod (`pod4.app.loxo.co/<slug>`)."""

    name = "loxo"
    kind = "ats"
    url_patterns = (re.compile(r"((?:[\w-]+\.)*app\.loxo\.co/[\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        base = f"https://{task.board.strip('/')}"
        resp = await get_page(http, base)
        urls = links(resp.text, base, lambda h: bool(_TOKEN.search(h)))
        agency = name_from_slug(task.board.strip("/").rsplit("/", 1)[-1])
        for chunk in chunks(urls, start_page):
            stubs = await asyncio.gather(
                *(self.posting(http, u, task.board, agency) for u in chunk)
            )
            yield [s for s in stubs if s]

    @staticmethod
    async def posting(http: Http, url: str, board: str, agency: str) -> JobStub | None:
        html = await page_text(http, url)
        if not html or not (ident := job_id(url)):
            return None
        tree = LexborHTMLParser(html)
        title = _meta(tree, "og:title")
        if not title:  # "Role | Agency" document title
            head = tree.css_first("title")
            title = " ".join((head.text() if head else "").split()).rsplit(" | ", 1)[0]
        body = _body(tree)
        if not title and not body:  # not a rendered job page
            return None
        location = _location(_meta(tree, "og:description"))
        return JobStub(
            source="loxo",
            url=url,
            title=title,
            company=agency,  # a hub board lists clients' roles; the page names the agency
            location=location,
            description=strip_html(body),
            ats="loxo",
            apply_url=url,
            remote=remote_from_text(location),
            extra={"board": board, "id": ident},
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if stub.description:
            return stub
        html = await page_text(http, stub.url)
        text = strip_html(_body(LexborHTMLParser(html))) if html else ""
        return stub.model_copy(update={"description": text}) if text else stub
