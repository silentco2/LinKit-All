"""TalentLyft career sites ({board}.talentlyft.com): sitemap.xml lists the /jobs/<slug>-<code>
postings and each page carries a schema.org JobPosting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import fetch_html, get_page, paged_postings, sitemap_locs
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug, posting_stub

# the code is the slug's last hyphen segment; the listing root and section pages have none
_CODE = re.compile(r"/jobs/.+-([A-Za-z0-9]{3,})$")


class TalentLyft(Source):
    name = "talentlyft"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.talentlyft\.com", re.I),)
    cdx_hosts = ("*.talentlyft.com",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.lower()
        sitemap = (await get_page(http, f"https://{board}.talentlyft.com/sitemap.xml")).text
        urls = [u for u in dict.fromkeys(sitemap_locs(sitemap)) if _CODE.search(u.split("?")[0])]

        async def build(url: str) -> JobStub | None:
            html, m = await fetch_html(http, url), _CODE.search(url.split("?")[0])
            if html is None or m is None:
                return None
            return posting_stub(
                html, source=self.name, url=url, board=board, id=m[1],
                company=name_from_slug(board),
            )  # fmt: skip

        async for stubs in paged_postings(urls, start_page, build):
            yield stubs
