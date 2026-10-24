"""Betterteam career sites ({board}.betterteam.com): the root page links each posting and each
posting page carries a schema.org JobPosting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import html_to_text

PAGE = 10  # job pages per checkpoint
# A posting permalink is one path segment ending in the numeric id: /bartender-21
_SLUG = re.compile(r"^/([a-z0-9][a-z0-9-]*-\d+)$")


def job_links(html: str, base: str) -> list[str]:
    """Absolute, de-duplicated posting URLs linked from the listing page."""
    found: dict[str, None] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        url = urljoin(base, a.attributes["href"] or "")
        if _SLUG.match(urlsplit(url).path) and urlsplit(url).netloc == urlsplit(base).netloc:
            found[url.split("#")[0].split("?")[0]] = None
    return list(found)


class Betterteam(Source):
    name = "betterteam"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.betterteam\.com", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        base = f"https://{task.board.lower()}.betterteam.com/"
        await http.allowed(base)
        resp = await http.get(base)
        resp.raise_for_status()
        # The root page renders the whole board, so a tenant larger than it holds is truncated.
        urls = job_links(resp.text, base)
        for page in range(start_page, (len(urls) + PAGE - 1) // PAGE):
            stubs = []
            for url in urls[page * PAGE : (page + 1) * PAGE]:
                if stub := await self.posting(http, url, task.board):
                    stubs.append(stub)
            yield stubs

    async def posting(self, http: Http, url: str, board: str) -> JobStub | None:
        await http.allowed(url)
        resp = await http.get(url)
        if resp.status_code in (404, 410):
            return None
        resp.raise_for_status()
        found = job_postings(resp.text)[:1]
        if not found:
            return None
        p = found[0]
        stub = to_stub(p, "betterteam", url, "betterteam")
        org = p.get("hiringOrganization")
        slug = _SLUG.match(urlsplit(url).path)
        return stub.model_copy(
            update={
                "title": " ".join(str(p.get("title") or "").split()),
                "company": (org.get("name") if isinstance(org, dict) else "") or board.title(),
                "description": html_to_text(p.get("description") or "", escaped=True),
                "remote": remote_from_text(stub.location),
                "extra": {"board": board, "id": slug[1] if slug else ""},
            }
        )
