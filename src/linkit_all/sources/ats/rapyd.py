"""Rapyd's own careers site (www.rapyd.net, WordPress): the careers-search page links each position
page, which is plain server-rendered HTML. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f13 import get_page, name_from_host
from linkit_all.sources.ats._f16 import links, page_text
from linkit_all.sources.ats._f17 import hydrate, text_of
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

LIST = "https://{host}/company/careers-search/"
PAGE = 20  # positions per yielded page: their detail fetches run together
_SLUG = re.compile(r"/company/careers/positions/([^/?#]+)")


def slug(url: str) -> str:
    m = _SLUG.search(url)
    return m.group(1) if m else ""


class Rapyd(Source):
    """The board is the careers host (`www.rapyd.net`). There is no structured data: title,
    location and body are read by their CSS classes from each position page."""

    name = "rapyd"
    kind = "ats"
    url_patterns = (re.compile(r"([\w.-]*rapyd\.net)/company/careers", re.I),)
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board.strip().lower()
        if "." not in host or re.search(r"[/:?#@\s]", host):
            raise ValueError(f"rapyd: board {task.board!r} is not a careers host")
        listing = (await get_page(http, LIST.format(host=host))).text
        urls = links(listing, f"https://{host}/", lambda h: bool(_SLUG.search(h)))
        company = name_from_host(host)

        async def build(url: str) -> JobStub | None:
            html = await page_text(http, url)
            if html is None:
                return None
            tree = LexborHTMLParser(html)
            title = text_of(tree.css_first("h1"))
            if not title:  # a page without a heading is a layout or error page
                return None
            where = text_of(tree.css_first(".country-term"))
            body = tree.css_first(".single-career-position__main")
            return JobStub(
                source="rapyd",
                url=url,
                title=title,
                company=company,
                location=where,
                description=html_to_text(body.html or "") if body else "",
                ats="rapyd",
                apply_url=url,
                # Only the location can say remote: a title like "Remote Support" would mislead.
                remote=remote_from_text(where),
                extra={"board": host, "id": slug(url)},
            )

        async for page in hydrate(urls, start_page, build, PAGE):
            yield page
