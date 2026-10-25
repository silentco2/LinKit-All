"""Avito careers (career.avito.com): the sitemap index lists the vacancy pages, each carrying a
schema.org JobPosting. Single-company plugin. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f13 import fetch_all, get_page
from linkit_all.sources.ats._f16 import CHUNK, chunks, ld_stub
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.companies._f41 import ats_of, remote_ru, sitemap_urls
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

SITEMAP = "https://career.avito.com/sitemap.xml"
# /vacancies/<category>/<id>/ : the category page has no trailing id
_VACANCY = re.compile(r"/vacancies/[^/]+/(\d+)")
_TITLE_CITY = re.compile(r"в городе\s+(.+?)\s*$")


def parse_vacancy(html: str, url: str) -> JobStub | None:
    m = _VACANCY.search(url)
    postings = job_postings(html)
    stub = (
        ld_stub(postings[0], source="avito", url=url, company="Avito", escaped=True,
                extra={"id": m[1]})
        if m and postings
        else None
    )  # fmt: skip
    if not stub:
        return None
    # The JobPosting names the head-office city even for remote roles; the page title ends with
    # the real one ("... в городе Удалённая работа").
    title = LexborHTMLParser(html).css_first("title")
    city = _TITLE_CITY.search(" ".join(title.text().split())) if title else None
    place = postings[0].get("jobLocation")
    place = place[0] if isinstance(place, list) and place else place
    address = place.get("address") if isinstance(place, dict) else None
    head_office = str(address.get("addressLocality") or "") if isinstance(address, dict) else ""
    location = city[1] if city else head_office
    return stub.model_copy(
        update={
            "location": location,
            "ats": ats_of(url, "avito"),
            "remote": remote_ru(location, stub.title),
        }
    )


class Avito(Source):
    name = "avito"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "avito:careers")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        by_id: dict[str, str] = {}  # the same vacancy can sit under several categories
        for u in await sitemap_urls(http, SITEMAP):
            if m := _VACANCY.search(u):
                by_id.setdefault(m[1], u)
        for chunk in chunks(sorted(by_id.values()), start_page, CHUNK):
            yield await fetch_all(http, list(chunk), parse_vacancy)

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        full = (
            None
            if stub.description
            else parse_vacancy((await get_page(http, stub.url)).text, stub.url)
        )
        return stub.model_copy(update={"description": full.description}) if full else stub
