"""Radancy (TalentBrew) career sites: the site's sitemap.xml lists the postings and each posting
page carries a schema.org JobPosting. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import get_page, hydrate, page_text, sitemap_locs
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import ld_stub, name_from_host

SITEMAP = "https://{host}/sitemap.xml"
PAGE = 20  # postings per yielded page: their detail fetches run together
# A posting is /job/<place>/<slug>/<site id>/<job id>; /category/ and landing pages have no job id.
_JOB = re.compile(r"/job/.*/(\d+)/?$")
_DATE = re.compile(r"^\s*(\d{4})-(\d{1,2})-(\d{1,2})")


def job_id(url: str) -> str:
    """The trailing numeric posting id of a job URL; "" when the URL is not a posting."""
    m = _JOB.search(url.split("?")[0])
    return m.group(1) if m else ""


def posted(value: Any) -> datetime | None:
    """datePosted is not zero-padded ("2026-6-17")."""
    m = _DATE.match(value) if isinstance(value, str) else None
    if not m:
        return None
    year, month, day = map(int, m.groups())
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def without_numeric_regions(posting: dict[str, Any]) -> dict[str, Any]:
    """Some tenants send addressRegion as a bare code ("10"), which is noise in a location."""
    places = posting.get("jobLocation")
    places = places if isinstance(places, list) else [places] if places else []
    cleaned = []
    for place in places:
        addr = (place or {}).get("address")
        if isinstance(addr, dict) and str(addr.get("addressRegion", "")).isdigit():
            place = {**place, "address": {**addr, "addressRegion": None}}
        cleaned.append(place)
    return {**posting, "jobLocation": cleaned}


class Radancy(Source):
    """The board is the career site's host (`careers.ing.com`)."""

    name = "radancy"
    kind = "ats"
    url_patterns = (
        re.compile(
            r"https?://([\w.-]+)/(?:[a-z]{2}(?:-[a-z]{2})?/)?job/[^/\s\"'<>]+/[^/\s\"'<>]+/\d+/\d+",
            re.I,
        ),
    )
    parallel = 2

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host = task.board.strip().lower()
        if "." not in host or re.search(r"[/:?#@\s]", host):
            raise ValueError(f"radancy: board {task.board!r} is not a career-site host")
        locs = [
            u
            for u in sitemap_locs((await get_page(http, SITEMAP.format(host=host))).text)
            if job_id(u)
        ]
        company = name_from_host(host)

        async def build(url: str) -> JobStub | None:
            html = await page_text(http, url)
            found = job_postings(html)[:1] if html else []
            if not found:
                return None
            stub = ld_stub(
                without_numeric_regions(found[0]),
                source="radancy",
                url=url,
                company=company,
                extra={"board": host, "id": job_id(url)},
                escaped=True,
            )
            return stub and stub.model_copy(
                update={"posted_at": posted(found[0].get("datePosted"))}
            )

        async for page in hydrate(locs, start_page, build, PAGE):
            yield page
