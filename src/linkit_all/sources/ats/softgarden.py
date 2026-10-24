"""softgarden career sites ({board}.softgarden.io): the root page links every open posting and each
posting page carries a schema.org JobPosting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.ats._f15 import fetch_html, get_page, paged_postings, posting_stub
from linkit_all.sources.ats._f16 import links
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http

_ID = re.compile(r"/job/(\d+)(?:[/?#]|$)")  # /job/<id>/<slug>?jobDbPVId=<n>


class Softgarden(Source):
    name = "softgarden"
    kind = "ats"
    url_patterns = (re.compile(r"([\w-]+)\.softgarden\.io", re.I),)
    cdx_hosts = ("*.softgarden.io",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        base = f"https://{task.board.lower()}.softgarden.io/"
        # ponytail: the first listing page only; later pages load through a Wicket AJAX callback
        urls = links((await get_page(http, base)).text, base, lambda h: bool(_ID.search(h)))

        async def build(url: str) -> JobStub | None:
            html, m = await fetch_html(http, url), _ID.search(url)
            if html is None or m is None:
                return None
            return posting_stub(
                html, source=self.name, url=url, board=task.board, id=m[1],
                company=name_from_slug(task.board),
            )  # fmt: skip

        async for stubs in paged_postings(urls, start_page, build):
            yield stubs
