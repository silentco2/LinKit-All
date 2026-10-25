"""GeekHunter career boards (geekhunter.com, Brazil): the board page lists its postings in an
ItemList JSON-LD block and each posting page carries a JobPosting block. Logic adapted from
freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import fetch_all, get_page, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.parsing import name_from_slug

CHUNK = 15  # posting pages read together per page of stubs
_SLUG = re.compile(r"/jobs/([^/?#]+)$")


def listing_urls(html: str) -> list[str]:
    node = LexborHTMLParser(html).css_first("script#itemList")
    try:
        items = json.loads(node.text(deep=True)).get("itemListElement", []) if node else []
    except ValueError:
        return []
    return [i["url"] for i in items if isinstance(i, dict) and i.get("url")]


def parse_job(html: str, url: str, board: str) -> JobStub | None:
    m = _SLUG.search(url)
    postings = job_postings(html)
    if not m or not postings:
        return None
    p = postings[0]
    stub = to_stub(p, "geekhunter", url, "geekhunter")
    # A fully remote posting simply has no jobLocation; there is no explicit flag.
    remote = "remote" if not p.get("jobLocation") else stub.remote
    return stub.model_copy(
        update={
            "company": stub.company if stub.company != "Unknown" else name_from_slug(board),
            "description": strip_html(p.get("description") or "", escaped=True),
            "remote": remote,
            "extra": {**stub.extra, "board": board, "id": m[1]},
        }
    )


class GeekHunter(Source):
    """The board is the company slug in `geekhunter.com/pt/<board>/jobs`."""

    name = "geekhunter"
    kind = "ats"
    url_patterns = (re.compile(r"geekhunter\.com/(?:pt/)?([\w-]+)/jobs", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        listing = f"https://www.geekhunter.com/pt/{task.board}/jobs"
        urls = listing_urls((await get_page(http, listing)).text)
        for i in range(start_page * CHUNK, len(urls), CHUNK):
            yield await fetch_all(
                http, urls[i : i + CHUNK], lambda h, u: parse_job(h, u, task.board)
            )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        full = parse_job((await get_page(http, stub.url)).text, stub.url, "")
        return stub.model_copy(update={"description": full.description}) if full else stub
