"""Freshteam (Freshworks ATS) career sites: a paged /jobs listing, a JobPosting block per job page.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import fetch_all, get_page, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub

MAX_PAGES = 100
# /jobs/<12-char id>/<slug>: the id is a fixed-length token, which keeps /jobs/search out.
_ID = re.compile(r"/jobs/([A-Za-z0-9_-]{12})(?:[/?#]|$)")


def job_links(html: str, base: str) -> list[str]:
    seen: dict[str, None] = {}
    for a in LexborHTMLParser(html).css("a[href]"):
        href = a.attributes.get("href") or ""
        if _ID.search(href):
            parts = urlsplit(urljoin(base, href))
            seen[f"{parts.scheme}://{parts.netloc}{parts.path}"] = None
    return list(seen)


def parse_job(html: str, url: str, board: str) -> JobStub | None:
    m = _ID.search(url)
    postings = job_postings(html)
    if not m or not postings:
        return None
    p = postings[0]
    posted = (p.get("datePosted") or "").replace(" UTC", "+00:00")  # "2026-06-17 20:44:40 UTC"
    stub = to_stub({**p, "datePosted": posted}, "freshteam", url, "freshteam")
    remote = str(p.get("remote")).strip().lower() == "true"  # a string, not a bool
    return stub.model_copy(
        update={
            "description": strip_html(p.get("description") or "", escaped=True),  # entity-encoded
            "posted_at": from_iso(posted) if posted else None,
            "remote": "remote" if remote else stub.remote,
            "extra": {**stub.extra, "board": board, "id": m[1]},
        }
    )


class Freshteam(Source):
    """The board is the tenant subdomain: `<board>.freshteam.com`."""

    name = "freshteam"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([\w-]+)\.freshteam\.com", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        base = f"https://{task.board}.freshteam.com/jobs"
        done: set[str] = set()  # a board that serves the same page for any ?page=N adds nothing
        for page in range(start_page + 1, MAX_PAGES + 1):
            html = (await get_page(http, f"{base}?page={page}")).text
            urls = [u for u in job_links(html, base) if u not in done]
            if not urls:
                return
            done.update(urls)
            yield await fetch_all(http, urls, lambda h, u: parse_job(h, u, task.board))

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        full = parse_job((await get_page(http, stub.url)).text, stub.url, "")
        return stub.model_copy(update={"description": full.description}) if full else stub
