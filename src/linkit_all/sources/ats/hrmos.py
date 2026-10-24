"""HRMOS career pages (hrmos.co, a Japanese multi-tenant ATS): a paged job listing and a schema.org
JobPosting on each job page. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f13 import get_page, name_from_slug
from linkit_all.sources.ats._f15 import fetch_html, posting_stub
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http

MAX_PAGES = 50  # the largest known board needs 5 pages of 100
LIST = "https://hrmos.co/pages/{board}/jobs"


def job_links(html: str, board: str) -> list[str]:
    """Absolute, de-duplicated /pages/<board>/jobs/<id> links. The literal `jobs` segment keeps
    the site's own single-segment navigation links out."""
    path = re.compile(rf"^/pages/{re.escape(board)}/jobs/[^/]+$", re.I)
    found: dict[str, None] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        parts = urlsplit(urljoin(LIST.format(board=board), a.attributes["href"] or ""))
        if parts.netloc in ("hrmos.co", "www.hrmos.co") and path.match(parts.path):
            found[f"https://hrmos.co{parts.path}"] = None
    return list(found)


class Hrmos(Source):
    """The board is the company's HRMOS slug (a vanity name or a numeric id)."""

    name = "hrmos"
    kind = "ats"
    url_patterns = (re.compile(r"hrmos\.co/pages/([\w.-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board, seen = task.board, set[str]()
        for page in range(start_page + 1, MAX_PAGES + 1):
            html = (await get_page(http, f"{LIST.format(board=board)}?page={page}")).text
            fresh = [u for u in job_links(html, board) if u not in seen]
            if not fresh:  # an empty page, or one clamped to the last page: the end
                return
            seen.update(fresh)
            stubs = []
            for url in fresh:
                page_html = await fetch_html(http, url)
                if page_html is None:
                    continue
                stub = posting_stub(
                    page_html, source=self.name, url=url, board=board, id=url.rsplit("/", 1)[1],
                    company=name_from_slug(board), escaped=False,
                )  # fmt: skip
                if stub:
                    stubs.append(stub)
            yield stubs
