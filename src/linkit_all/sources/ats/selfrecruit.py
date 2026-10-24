"""selfrecruit.ge ("Self.hr"), a Georgian multi-tenant ATS with no API or JSON-LD: an offset-paged
listing and posting pages read by their CSS classes. Logic adapted from freehire (MIT)."""

import asyncio
import re
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.ats._f16 import links, page_text
from linkit_all.sources.ats._f17 import text_of
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

BASE = "https://{board}.selfrecruit.ge/"
PAGE = 10  # postings per listing page (offsets 0, 10, 20...)
MAX_PAGES = 100
# A posting sits at the tenant root as a bare UUID; /cv, /vacancies/10 or /articles/<uuid> are not.
_ID = re.compile(
    r"^/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:$|[/?#])", re.I
)


def job_id(url: str) -> str:
    m = _ID.match(urlsplit(url).path)
    return m.group(1) if m else ""


class SelfRecruit(Source):
    """The board is the tenant subdomain (`dressup.selfrecruit.ge`). A page past the last one
    redirects to the tenant root, so a page that adds no new posting ends the board."""

    name = "selfrecruit"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w-])(?!www\.)([\w-]+)\.selfrecruit\.ge", re.I),)
    cdx_hosts = ("*.selfrecruit.ge",)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        base = BASE.format(board=task.board)
        company = name_from_slug(task.board)
        seen: set[str] = set()
        for page in range(start_page, MAX_PAGES):
            html = await page_text(http, f"{base}vacancies/{page * PAGE}")
            if html is None:
                raise ValueError(f"selfrecruit: {task.board}: listing page {page} is unreadable")
            urls = [u for u in links(html, base, lambda h: bool(job_id(h))) if u not in seen]
            if not urls:
                return
            seen.update(urls)
            built = await asyncio.gather(*(self.build(http, u, task.board, company) for u in urls))
            yield [s for s in built if s is not None]

    @staticmethod
    async def build(http: Http, url: str, board: str, company: str) -> JobStub | None:
        html = await page_text(http, url)
        if html is None:
            return None
        tree = LexborHTMLParser(html)
        title = text_of(tree.css_first(".vacancy_title_inner"))
        body = tree.css_first(".pub_vac_text_detail")
        if not title or body is None:  # an answer without posting markup is not a posting
            return None
        return JobStub(
            source="selfrecruit",
            url=url,
            title=title,
            company=company,
            description=html_to_text(body.html or ""),
            ats="selfrecruit",
            apply_url=url,
            remote=remote_from_text(title),
            extra={"board": board, "id": job_id(url)},
        )
