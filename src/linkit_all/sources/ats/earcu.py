"""eArcu career sites (UK ATS): every client runs on its own host and publishes /jobs/rss.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime
from email.utils import parsedate_to_datetime

from lxml import etree

from linkit_all.sources.ats._f12 import get_page, name_from_host
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.text import html_to_text

# /jobs/vacancy/<slug>/<id>/description/ ; anchored so an earlier number is not taken for the id
_ID = re.compile(r"/(\d+)/description/?$")
_REF = re.compile(r"\s*\(\d+\)\s*$")  # the " (7367)" reference eArcu adds to feed titles
_LOCATION = re.compile(r"Location:\s*(.+?),\s*eArcu Vacancy Reference:")
_COUNTRY = re.compile(r"Country:\s*([^,]+)")
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)


class Earcu(Source):
    """The board is the full careers host (`careers.cambridge.org`), not a subdomain."""

    name = "earcu"
    kind = "ats"
    url_patterns = (re.compile(r"(?:https?://)?([\w.-]+)/jobs/(?:vacancy/[^/\s]+/\d+/|rss)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the feed is not paged
            return
        feed = etree.fromstring(
            (await get_page(http, f"https://{task.board}/jobs/rss")).content, _PARSER
        )
        stubs = []
        for item in feed.iterfind("channel/item"):
            link = (item.findtext("link") or "").strip()
            m = _ID.search(link)
            if not m:  # no stable posting id: not a vacancy
                continue
            # The text before <div id="rssjobdesc"> is "Key: value, ..." metadata; the rest is
            # the body. Splitting first keeps a "Location:" inside the body from being read.
            raw = item.findtext("description") or ""
            meta, sep, body = raw.partition('<div id="rssjobdesc"')
            location = _location(meta)
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link,
                    title=_REF.sub("", item.findtext("title") or "").strip(),
                    company=name_from_host(task.board),
                    location=location,
                    description=html_to_text(sep + body) if body else "",
                    posted_at=_date(item.findtext("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote=remote_from_text(location),
                    extra={"board": task.board, "id": m[1]},
                )
            )
        yield stubs

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        """Items without an inline body fall back to the page's JobPosting JSON-LD."""
        if stub.description:
            return stub
        postings = job_postings((await get_page(http, stub.url)).text)
        desc = (postings[0].get("description") if postings else "") or ""
        return stub.model_copy(update={"description": html_to_text(desc, escaped=True)})


def _location(meta: str) -> str:
    m = _LOCATION.search(meta) or _COUNTRY.search(meta)
    return m[1].strip() if m else ""


def _date(value: str | None) -> datetime | None:
    """eArcu writes RFC 822 dates with a literal "Z" zone, sometimes with an unpadded day."""
    if not value:
        return None
    try:
        return from_iso(parsedate_to_datetime(value.strip()).isoformat())
    except (TypeError, ValueError):
        return None
