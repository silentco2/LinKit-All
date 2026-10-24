"""Self-hosted Odoo recruitment sites (website_hr_recruitment): /jobs lists every position and each
/jobs/detail/<slug>-<id> page carries schema.org JobPosting microdata. Logic adapted from freehire
(MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.ats._f12 import get_page, name_from_host
from linkit_all.sources.ats._f16 import page_text, when
from linkit_all.sources.ats._f17 import hydrate, text_of
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

CHUNK = 20  # posting pages fetched together per page of stubs
# /jobs/<slug>-<id> or /jobs/detail/<slug>-<id>, any language prefix; the filter links Odoo adds
# (/jobs/country/egypt-62) have a second segment and are not postings.
_JOB = re.compile(r"/jobs/(?:detail/)?[^/?#]*-(\d+)/?(?:[?#]|$)")


def parse_posting(html: str, url: str, host: str) -> JobStub | None:
    tree = LexborHTMLParser(html)
    body = tree.css_first('[itemprop="description"]')
    description = html_to_text(body.html or "") if body else ""
    title = text_of(tree.css_first("h1")) or text_of(tree.css_first('[itemprop="title"]'))
    if not description or not title:  # not a JobPosting page (or an empty stub)
        return None
    place = [
        text_of(tree.css_first(f'[itemprop="{p}"]')) for p in ("addressLocality", "addressCountry")
    ]
    location = ", ".join(p for p in place if p)
    stamp = tree.css_first('[itemprop="datePosted"]')
    attrs = stamp.attributes if stamp else {}
    return JobStub(
        source="odoo",
        url=url,
        title=title,
        company=name_from_host(host),
        location=location,
        description=description,
        posted_at=when(attrs.get("datetime") or attrs.get("content")),
        ats="odoo",
        apply_url=url,
        remote=remote_from_text(title, location),
        extra={"board": host, "id": _JOB.search(url)[1]},  # type: ignore[index]
    )


class Odoo(Source):
    """The board is the careers host (`jobs.acme.com` or `acme.com`); sites are self-hosted, so
    there is no URL pattern: list a site as `odoo:jobs.acme.com`."""

    name = "odoo"
    kind = "ats"

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board.strip().lower()
        if "." not in host or re.search(r"[/:?#@\s]", host):
            raise ValueError(f"odoo: board {task.board!r} is not a careers host")
        base = f"https://{host}/jobs"
        listing = LexborHTMLParser((await get_page(http, base)).text)
        urls: dict[str, None] = {}
        for a in listing.css("a[href]"):
            href = (a.attributes.get("href") or "").strip()
            link = urlsplit(urljoin(base, href))
            if _JOB.search(link.path) and (link.hostname or "").lower() == host:
                urls[f"https://{host}{link.path}"] = None
        async for page in hydrate(
            list(urls), start_page, lambda u: self.posting(http, u, host), CHUNK
        ):
            yield page

    async def posting(self, http: Http, url: str, host: str) -> JobStub | None:
        html = await page_text(http, url)
        return parse_posting(html, url, host) if html else None
