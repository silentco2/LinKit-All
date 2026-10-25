"""Torre (torre.ai), a Latin-American-born talent marketplace whose postings each name their own
employer: the sitemaps list the posts and each page carries a JobPosting block.
Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import (
    page_text,
    posting_pages,
    sitemap_by_date,
    sitemap_locs,
    sitemap_text,
)
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import ld_stub
from linkit_all.sources.tasks import feed_task

INDEX = "https://torre.ai/sitemap-index.xml"
_POST = re.compile(r"^https://torre\.ai/post/([A-Za-z0-9]+)(?:-[^/?#]*)?$")


def place(posting: dict[str, Any]) -> str:
    """The posting's places as "city, region, country; ..."; a street address that is only a
    place name stands in for a missing city, and a remote role reads "Remote, <where>"."""
    places = posting.get("jobLocation") or []
    parts = []
    for p in places if isinstance(places, list) else [places]:
        a = (p or {}).get("address") or {}
        if not isinstance(a, dict):
            continue
        street = (a.get("streetAddress") or "").strip()
        city = (a.get("addressLocality") or "").strip() or (
            "" if re.search(r"\d", street) else street
        )
        names = (
            city,
            (a.get("addressRegion") or "").strip(),
            (a.get("addressCountry") or "").strip(),
        )
        parts.append(", ".join(dict.fromkeys(n for n in names if n)))
    where = "; ".join(dict.fromkeys(p for p in parts if p))
    if posting.get("jobLocationType") == "TELECOMMUTE":
        return f"Remote, {where or 'Worldwide'}"
    return where


class Torre(Source):
    name = "torre"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        texts = []
        for sub in sitemap_locs(await sitemap_text(http, INDEX)):
            try:
                texts.append(await sitemap_text(http, sub))
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (404, 410):  # a retired sitemap is skipped
                    raise
        by_id: dict[str, str] = {}  # one posting can sit in several sitemaps
        for url in sitemap_by_date("".join(texts), lambda u: bool(_POST.match(u))):
            by_id.setdefault(_POST.match(url)[1], url)  # type: ignore[index]

        async def build(url: str) -> JobStub | None:
            text = await page_text(http, url)
            postings = job_postings(text) if text else []
            if not postings or not (m := _POST.match(url)):  # a closed post has no JobPosting
                return None
            stub = ld_stub(
                postings[0], source=self.name, url=url, company="", extra={"id": m[1]}, escaped=True
            )
            if stub is None or not stub.company or not stub.description:
                return None
            update: dict[str, Any] = {"location": place(postings[0])}
            if (stub.salary_min, stub.salary_max) == (1, 1000):  # Torre's "unset" placeholder
                update |= {"salary_min": None, "salary_max": None}
            return stub.model_copy(update=update)

        async for page in posting_pages(list(by_id.values()), start_page, task.limit, build):
            yield page
