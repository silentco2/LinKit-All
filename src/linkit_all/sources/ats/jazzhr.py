"""JazzHR career sites ({board}.applytojob.com): the /apply listing links every open posting, and
each posting page carries a schema.org JobPosting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import fetch_html, get_page, paged_postings
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug, posting_stub

_TOKEN = re.compile(r"/apply/([A-Za-z0-9]+)/")  # the public permalink token of a posting


def job_links(html: str, base: str) -> list[str]:
    """Absolute, de-duplicated /apply/<token>/<slug> links (a card links the job twice)."""
    found: dict[str, None] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        href = a.attributes["href"] or ""
        if _TOKEN.search(href):
            found[urljoin(base, href).split("#")[0]] = None
    return list(found)


class JazzHR(Source):
    name = "jazzhr"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.applytojob\.com", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = f"{task.board.lower()}.applytojob.com"
        listing = await get_page(http, f"https://{host}/apply")  # one page lists everything
        links = job_links(listing.text, f"https://{host}/")

        async def build(url: str) -> JobStub | None:
            html, m = await fetch_html(http, url), _TOKEN.search(url)
            if html is None or m is None:
                return None
            return posting_stub(
                html, source=self.name, url=url, board=task.board, id=m[1],
                company=name_from_slug(task.board),
            )  # fmt: skip

        async for stubs in paged_postings(links, start_page, build):
            yield stubs
