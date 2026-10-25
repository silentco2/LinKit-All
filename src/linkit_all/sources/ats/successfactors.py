"""SAP SuccessFactors career sites (board = the careers host): job_sitemap.xml lists the postings
and each page carries schema.org JobPosting microdata. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import fetch_html, get_page, paged_postings, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_host, node_text, when

_ID = re.compile(r"/(\d+)(?:-[^/?#]*)?/?$")  # .../98012-en_GB or .../12345/
_URL = re.compile(r"<url>(.*?)</url>", re.S)
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_LASTMOD = re.compile(r"<lastmod>\s*([^<]+?)\s*</lastmod>")


class SuccessFactors(Source):
    name = "successfactors"
    kind = "ats"
    # Hosts are the customers' own, so only the locale suffix SuccessFactors puts on a job id is
    # recognised in a pasted URL; for any other, use `successfactors:<careers host>`.
    url_patterns = (re.compile(r"([\w.-]+)/job/[^/\s]+/\d+-[a-z]{2}_[A-Z]{2}\b"),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        sitemap = (await get_page(http, f"https://{task.board}/job_sitemap.xml")).text
        entries: dict[str, str | None] = {}  # url -> lastmod
        for block in _URL.findall(sitemap):
            loc, mod = _LOC.search(block), _LASTMOD.search(block)
            if loc and _ID.search(url := loc[1].replace("&amp;", "&")):
                entries.setdefault(url, mod[1] if mod else None)
        urls = list(entries)

        async def build(url: str) -> JobStub | None:
            html = await fetch_html(http, url)
            m = _ID.search(url)
            if html is None or m is None:
                return None
            tree = LexborHTMLParser(html)
            title_node, body = (
                tree.css_first('[itemprop="title"]'),
                tree.css_first('[itemprop="description"]'),
            )
            if title_node is None and body is None:  # not a posting page
                return None
            og = tree.css_first('meta[property="og:title"]')
            title = node_text(title_node) or ((og.attributes.get("content") if og else "") or "")
            if not title.strip():
                return None
            # The microdata carries no location; the description is all there is to match on.
            return JobStub(
                source=self.name,
                url=url,
                title=title.strip(),
                company=name_from_host(task.board),
                description=strip_html(body.html or "") if body else "",
                posted_at=when(entries[url]),
                ats=self.name,
                apply_url=url,
                extra={"board": task.board, "id": m[1]},
            )

        async for stubs in paged_postings(urls, start_page, build):
            yield stubs
