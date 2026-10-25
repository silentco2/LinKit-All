"""Potok (potok.io), a Russian ATS: each tenant's server-rendered /open/jobs/ page lists every open
posting, and the posting page holds the body. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug, node_text
from linkit_all.sources.text import html_to_text

LIST = "https://{board}.potok.io/open/jobs/"
JOB_URL = "https://{board}.potok.io/open/jobs/{id}"
_JOB = re.compile(r"//([\w-]+)\.potok\.io/open/jobs/(\d+)", re.I)
_HREF = re.compile(r"/open/jobs/(\d+)$")
REMOTE_SCHEDULE = "Удаленная работа"  # the schedule picklist value that states remote work


class Potok(Source):
    """The board is the tenant subdomain (`skyeng.potok.io`). The list is one unpaginated page;
    neither page states a salary or a posting date."""

    name = "potok"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w-])(?!app\.|www\.)([\w-]+)\.potok\.io", re.I),)
    cdx_hosts = ("*.potok.io/open/jobs/*",)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        html = (await get_page(http, LIST.format(board=task.board))).text
        yield self.parse_list(html, task.board)

    def parse_list(self, html: str, board: str) -> list[JobStub]:
        tree = LexborHTMLParser(html)
        # A tenant with no openings still renders the wrapper; a page without it is not the
        # career page (a changed template), which must not read as "no jobs".
        if tree.css_first(".postings-wrapper") is None:
            raise ValueError(f"potok: {board}: the page carries no postings listing")
        company = name_from_slug(board)
        stubs = []
        for row in tree.css(".postings-wrapper .posting"):
            link = row.css_first("a.posting-title")
            m = _HREF.search(link.attributes.get("href") or "") if link else None
            title = node_text(link.css_first("h5")) if link else ""
            if not (link and m and title):
                continue
            where = node_text(link.css_first(".sort-by-location"))
            url = JOB_URL.format(board=board, id=m.group(1))
            stubs.append(
                JobStub(
                    source="potok",
                    url=url,
                    title=title,
                    company=company,
                    location=where,
                    ats="potok",
                    apply_url=url,
                    remote=remote_from_text(where),
                    extra={"board": board, "id": m.group(1)},
                )
            )
        return stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if not _JOB.search(stub.url):
            return stub
        tree = LexborHTMLParser((await get_page(http, stub.url)).text)
        body = tree.css_first(".plain-list")
        if body is None:
            return stub
        # The headline's categories are the city, then the schedule; only the schedule can say
        # remote.
        times = tree.css(".posting-headline .posting-category.sort-by-time")
        remote = (
            "remote" if len(times) > 1 and node_text(times[1]) == REMOTE_SCHEDULE else stub.remote
        )
        return stub.model_copy(
            update={"description": html_to_text(body.html or ""), "remote": remote}
        )
