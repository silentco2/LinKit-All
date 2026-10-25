"""DataArt careers (www.dataart.team): the sitemap lists the vacancy pages, each carrying a
schema.org JobPosting. Single-company plugin. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import CHUNK, chunks, fetch_all, get_page, sitemap_pages
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings
from linkit_all.sources.parsing import ats_of, ld_stub

SITEMAP = "https://www.dataart.team/sitemap.xml"
# English vacancy pages only: /xx/vacancies/... are translations, /vacancies is the listing.
_VACANCY = re.compile(r"^https?://www\.dataart\.team/vacancies/([a-z0-9]+)/?$")


def places(posting: dict[str, Any]) -> tuple[str, bool]:
    """("City, Country; ...", has a remote tag). DataArt leaks internal "Remote.XX" region codes
    into the address: they mark the role remote and are not shown as places."""
    rows = posting.get("jobLocation") or []
    out: list[str] = []
    remote = False
    for row in rows if isinstance(rows, list) else [rows]:
        addr = row.get("address") if isinstance(row, dict) else None
        if not isinstance(addr, dict):
            continue
        parts = [str(addr.get(k) or "") for k in ("addressLocality", "addressCountry")]
        remote = remote or any(p.startswith("Remote.") for p in parts)
        text = ", ".join(p for p in parts if p and not p.startswith("Remote."))
        if text and text not in out:
            out.append(text)
    return "; ".join(out), remote


def parse_vacancy(html: str, url: str) -> JobStub | None:
    m = _VACANCY.match(url)
    postings = job_postings(html)
    if not m or not postings:
        return None
    stub = ld_stub(postings[0], source="dataart", url=url, company="DataArt", escaped=True,
                   extra={"id": m[1]})  # fmt: skip
    if not stub:
        return None
    location, remote = places(postings[0])
    return stub.model_copy(
        update={
            "location": location,
            "ats": ats_of(url, "dataart"),
            "remote": "remote" if remote else remote_from_text(location),
        }
    )


class DataArt(Source):
    name = "dataart"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "dataart:vacancies")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        urls = sorted({u for u in await sitemap_pages(http, SITEMAP) if _VACANCY.match(u)})
        for chunk in chunks(urls, start_page, CHUNK):
            yield await fetch_all(http, list(chunk), parse_vacancy)

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        full = (
            None
            if stub.description
            else parse_vacancy((await get_page(http, stub.url)).text, stub.url)
        )
        return stub.model_copy(update={"description": full.description}) if full else stub
