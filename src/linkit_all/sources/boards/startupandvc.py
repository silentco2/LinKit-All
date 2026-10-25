"""Startup & VC (startupandvc.com), a curated venture-capital jobs board: the listing links each
vacancy page, which carries a JobPosting block, the rich description and the outbound "Apply now"
link to the original posting (often an ATS). Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, page_text, posting_pages, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import ats_of, ld_stub, links
from linkit_all.sources.tasks import feed_task

LIST = "https://www.startupandvc.com/venture-capital-jobs"
_SLUG = re.compile(r"/venture-capital-jobs/([a-z0-9][a-z0-9-]*)(?:$|[?#])")


def _date(value: str | None) -> datetime | None:
    """The site's "Jul 07, 2026"."""
    try:
        return datetime.strptime((value or "").strip(), "%b %d, %Y")
    except ValueError:
        return None


def _apply_link(html: LexborHTMLParser) -> str:
    """The "Apply now" target without the `?utm_source=...` tracking tail the site appends."""
    a = html.css_first("a.button-large")
    href = ((a.attributes.get("href") if a else "") or "").strip()
    return re.split(r"\?utm_source=", href, maxsplit=1)[0]


class StartupAndVC(Source):
    name = "startupandvc"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        listing = (await get_page(http, LIST)).text
        urls = links(listing, LIST + "/", lambda h: bool(_SLUG.search(h)))

        async def build(url: str) -> JobStub | None:
            text = await page_text(http, url)
            postings = job_postings(text) if text else []
            if not text or not postings or not (m := _SLUG.search(url)):
                return None
            doc = LexborHTMLParser(text)
            rich = doc.css_first(".w-richtext")  # the ld+json description is a one-line stub
            stub = ld_stub(
                postings[0], source=self.name, url=url, company="", extra={"id": m[1]}, escaped=True
            )
            if stub is None or not stub.company:
                return None
            apply = _apply_link(doc)
            return stub.model_copy(
                update={
                    "description": strip_html(rich.html or "")
                    if rich and rich.html
                    else stub.description,
                    "posted_at": _date(postings[0].get("datePosted")),
                    "apply_url": apply or url,
                    "ats": ats_of(apply, self.name),
                }
            )

        async for page in posting_pages(urls, start_page, task.limit, build):
            yield page
