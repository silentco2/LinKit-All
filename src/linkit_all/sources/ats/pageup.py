"""PageUp People career sites (careers.pageuppeople.com/<institution id>/), a multi-tenant ATS
common in AU/UK/NZ universities: the search endpoint answers a JSON envelope whose `results` is
an HTML fragment. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.common import XHR, hydrate
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.parsing import node_text
from linkit_all.sources.text import html_to_text

HOST = "https://careers.pageuppeople.com"
CHUNK = 20  # detail fetches together per page of stubs
_JOB = re.compile(r"/cw/en/job/(\d+)/")
# Tenants whose listing summary is a one-sentence teaser, not the posting (Flight Centre).
_ALWAYS_DETAIL = frozenset({"889"})


def parse_listing(fragment: str, board: str) -> list[JobStub]:
    """Postings of a search-results fragment. The row wrapper differs per tenant (<tr>, <li>,
    <div>), so it walks the stable a.job-link anchors and hands each one the location and summary
    that follow it, up to the next anchor."""
    if "<tr" in fragment:  # bare rows are meant for an existing <table>; without one they vanish
        fragment = f"<table>{fragment}</table>"
    jobs: list[dict[str, Any]] = []
    for node in LexborHTMLParser(fragment).css("a.job-link, .location, .jobs-summary, .summary, p"):
        classes = (node.attributes.get("class") or "").split()
        if node.tag == "a":
            href = node.attributes.get("href") or ""
            if m := _JOB.search(href):  # other job-links are navigation
                jobs.append(
                    {
                        "id": m[1],
                        "title": node_text(node),
                        "url": HOST + href,
                        "loc": "",
                        "text": "",
                    }
                )
        elif not jobs:
            continue
        elif "location" in classes:
            jobs[-1]["loc"] = jobs[-1]["loc"] or node_text(node)
        elif "summary" in classes or "jobs-summary" in classes or (node.tag == "p" and not classes):
            jobs[-1]["text"] = jobs[-1]["text"] or node_text(node)
    return [
        JobStub(
            source="pageup",
            url=j["url"],
            title=j["title"],
            company=f"PageUp {board}",  # the endpoint names no employer
            location=j["loc"],
            description=j["text"],
            ats="pageup",
            apply_url=j["url"],
            remote=remote_from_text(j["loc"]),
            extra={"board": board, "id": j["id"]},
        )
        for j in jobs
    ]


class PageUp(Source):
    """The board is the numeric institution id: `513` for careers.pageuppeople.com/513/."""

    name = "pageup"
    kind = "ats"
    url_patterns = (re.compile(r"careers\.pageuppeople\.com/(\d+)(?:/|\b)", re.I),)
    cdx_hosts = ("careers.pageuppeople.com/*",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.strip()
        if not board.isdigit():
            raise ValueError(f"pageup: board {task.board!r} is not an institution id")
        stubs = parse_listing(
            await self.envelope(http, f"{HOST}/{board}/cw/en/search/?page-items=1000"), board
        )

        # Tenants that list no summary keep the posting text on the job's own page.
        async def build(stub: JobStub) -> JobStub | None:
            if stub.description and board not in _ALWAYS_DETAIL:
                return stub
            return stub.model_copy(
                update={"description": await self.detail(http, stub.url) or stub.description}
            )

        async for page in hydrate(stubs, start_page, build, CHUNK):
            yield page

    @staticmethod
    async def envelope(http: Http, url: str) -> str:
        """The `results` fragment of an XHR answer. Without the header the site redirects to the
        full HTML page."""
        await http.allowed(url)
        resp = await http.get(url, headers=XHR)
        resp.raise_for_status()
        return str(resp.json().get("results") or "")

    async def detail(self, http: Http, url: str) -> str:
        """The posting text from the job page's #job-details block, "" when the page has none."""
        try:
            fragment = await self.envelope(http, url)
        except (Unsupported, httpx.HTTPError, RetryableStatus, ValueError, AttributeError):
            return ""
        block = LexborHTMLParser(fragment).css_first("#job-details")
        return html_to_text(block.html or "") if block else ""

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        if stub.description:
            return stub
        return stub.model_copy(update={"description": await self.detail(http, stub.url)})
