"""Northstone Holdings recruiting-brand career sites (Revun, EnzRossi's "Vetted", Langford): one
server-rendered template, a /<section>/ listing that links each posting page, which carries a
schema.org JobPosting. Logic adapted from freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from linkit_all.sources.ats._f13 import get_page, name_from_slug
from linkit_all.sources.ats._f16 import chunks, ld_stub, links, page_text
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings


def parse_board(board: str) -> tuple[str, str]:
    """`<host>/<section>` -> (host, section)."""
    host, _, section = board.strip().strip("/").partition("/")
    if not host or not section or "/" in section:
        raise ValueError(f"northstone: board {board!r} must be <host>/<section>")
    return host, section


def canonical(url: str) -> str:
    """The sites redirect a posting URL without its trailing slash; use the final form."""
    parts = urlsplit(url)
    return url if parts.path.endswith("/") else parts._replace(path=parts.path + "/").geturl()


class Northstone(Source):
    """The board is `<host>/<section>`: `www.revun.com/careers`, `vetted.enzrossi.com/positions`.
    The brands are listed one by one in `url_patterns`; any other can be added as `northstone:`
    plus its host and section."""

    name = "northstone"
    kind = "ats"
    url_patterns = (
        re.compile(r"((?:www\.)?revun\.com)/(careers)\b", re.I),
        re.compile(r"(vetted\.enzrossi\.com)/(positions)\b", re.I),
    )

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host, section = parse_board(task.board)
        base = f"https://{host}/{section}/"  # the slash is needed: without it the site redirects
        resp = await get_page(http, base)
        is_job = re.compile(rf"^/{re.escape(section)}/[^/?#]+/?$")
        urls = links(resp.text, base, lambda h: bool(is_job.match(urlsplit(h).path)))
        for chunk in chunks(urls, start_page):
            stubs = await asyncio.gather(*(self.posting(http, u, task.board, host) for u in chunk))
            yield [s for s in stubs if s]

    @staticmethod
    async def posting(http: Http, url: str, board: str, host: str) -> JobStub | None:
        url = canonical(url)
        html = await page_text(http, url)
        found = job_postings(html)[:1] if html else []
        ident = found and found[0].get("identifier")
        value = str(ident.get("value") or "").strip() if isinstance(ident, dict) else ""
        if not found or not value:  # a link that is no posting, or one with no stable id
            return None
        p = found[0]
        brand = name_from_slug(host.split(".")[-2] if "." in host else host)
        stub = ld_stub(
            p,
            source="northstone",
            url=url,
            company=brand,
            escaped=True,
            extra={"board": board, "id": value},
        )
        if not stub or stub.location:
            return stub
        # A fully remote posting has no jobLocation; the countries it accepts are the place.
        names = [
            str(c.get("name"))
            for c in p.get("applicantLocationRequirements") or []
            if c.get("name")
        ]
        return stub.model_copy(update={"location": ", ".join(names)})
