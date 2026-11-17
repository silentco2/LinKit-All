"""BWI GmbH (the German armed forces' IT service provider), self-hosted careers at
www.bwi.de/karriere/stellenangebote. The listing embeds one JSON-LD ItemList of every open
position, addresses only, so one request lists the board with titles rebuilt from the address
("...-m-w-d-69624" -> "... (m/w/d)"). `fetch_details` reads the posting page's JobPosting for
the real title, place, date and body. Logic adapted from career-ops (MIT)."""

import json
import re
from collections.abc import AsyncIterator, Iterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import clean, last_segment, safe_date
from linkit_all.sources.tasks import careers_task
from linkit_all.sources.text import html_to_text

LIST = "https://www.bwi.de/karriere/stellenangebote"
_JOB = re.compile(r"^https://www\.bwi\.de/karriere/stellenangebote/job/[^\s\"?#]+$")
_LD = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.I | re.S)
_GENDERED = re.compile(r"-(?:m-w-d|m-d-w|w-m-d|d-m-w)-?\d{4,6}$", re.I)
_TAIL = re.compile(r"-(?:m-w-d|m-d-w|w-m-d|d-m-w)?-?(\d{4,6})$", re.I)


def slug_title(url: str) -> str:
    slug = last_segment(url)
    core = _TAIL.sub("", slug)
    words = " ".join(w[:1].upper() + w[1:] for w in core.split("-") if w)
    return f"{words} (m/w/d)" if words and _GENDERED.search(slug) else words


def _urls(node: Any) -> Iterator[str]:
    """Every "url" string anywhere in a JSON-LD tree."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "url" and isinstance(value, str):
                yield value
            yield from _urls(value)
    elif isinstance(node, list):
        for item in node:
            yield from _urls(item)


class Bwi(Source):
    name = "bwi"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return careers_task(self.name)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the listing's ItemList holds the whole board
            return
        stubs = self.parse((await get_page(http, LIST)).text)
        if stubs:
            yield stubs

    def parse(self, html: str) -> list[JobStub]:
        urls: dict[str, None] = {}
        for block in _LD.findall(html):
            try:
                urls |= dict.fromkeys(u for u in _urls(json.loads(block)) if _JOB.match(u))
            except ValueError:
                continue
        stubs = []
        for url in urls:
            title, tail = slug_title(url), _TAIL.search(last_segment(url))
            if title:
                stubs.append(
                    JobStub(
                        source=self.name,
                        url=url,
                        title=title,
                        company="BWI GmbH",
                        ats=self.name,
                        apply_url=url,
                        extra={"id": tail[1] if tail else last_segment(url)},
                    )
                )
        return stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        page = await page_text(http, stub.url)
        found = job_postings(page)[:1] if page else []
        if not found:
            return stub
        p = found[0]
        loc = p.get("jobLocation")
        loc = loc[0] if isinstance(loc, list) and loc else loc
        city = (
            clean(((loc or {}).get("address") or {}).get("addressLocality"))
            if isinstance(loc, dict)
            else ""
        )
        update = {
            "title": clean(p.get("title")),
            "location": city,
            "posted_at": safe_date(p.get("datePosted")),
            "description": html_to_text(str(p.get("description") or "")),
        }
        return stub.model_copy(update={k: v for k, v in update.items() if v})
