"""IBM's careers catalogue, read from the site-search API that ibm.com/careers/search itself calls
(www-api.ibm.com): every open posting with its full text, so no posting page is fetched. A
single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, from_iso
from linkit_all.sources.common import paged
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import mode

HOST = "www-api.ibm.com"
PAGE = 100  # the API's ceiling: 101 is a 400
SEARCH = "https://{host}/search/api/v2"
JOB = "https://careers.ibm.com/careers/JobDetail?jobId={id}"
# The API returns no _source unless every field is named.
FIELDS = [
    "field_text_01",  # job id
    "title",
    "body",  # full text, newlines collapsed, the facet values appended
    "dcdate",  # YYYY-MM-DD
    "field_keyword_05",  # country name
    "field_keyword_08",  # area of work
    "field_keyword_17",  # "Hybrid", "Remote" or "" (on-site is never stated)
    "field_keyword_18",  # "Professional", "Entry Level" or "Internship"
    "field_keyword_19",  # "BARI, IT" or "Multiple Cities"
    "field_keyword_20",  # hiring legal entity
]
_CITY = re.compile(r"^(.+),\s*[A-Za-z]{2}$")
# The index flattens the page to one line, so a list survives only as "• item • item" (or ·, *, ●,
# ▪) between spaces of any kind, no-break ones included.
_BULLET = re.compile(r"[\s\u00a0]+[•·*●▪][\s\u00a0]+")


def location(city: str, country: str) -> str:
    """ "Bari, Italy" from the city facet "BARI, IT" and the country name; "Multiple Cities" names
    no place, so then the country alone."""
    city, country = city.strip(), country.strip()
    if not city or city.lower() == "multiple cities":
        return country
    m = _CITY.match(city)
    return f"{m[1].strip().title()}, {country}" if m and country else city


def description(p: dict[str, Any]) -> str:
    """The body without the facet values the index appends after it, bullets back on own lines."""
    body = (p.get("body") or "").strip()
    facets = [
        (p.get(k) or "").strip()
        for k in (
            "field_keyword_05",
            "field_keyword_08",
            "field_keyword_17",
            "field_keyword_18",
            "field_keyword_19",
            "field_keyword_20",
        )
    ]
    if suffix := " ".join(f for f in facets if f):
        body = body.removesuffix(suffix).strip()
    body = body.replace(
        "\u00e2\u20ac\u2122", "\u2019"
    )  # a right quote read as Windows-1252, the only mojibake seen
    body = _BULLET.sub("\n• ", body)
    return "\n".join(" ".join(line.split()) for line in body.splitlines() if line.strip())


class Ibm(Source):
    name = "ibm"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "ibm:careers", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        async def fetch(offset: int) -> tuple[list[dict[str, Any]], int | None]:
            body = {
                "appId": "careers",
                "scopes": ["careers2"],
                "query": {"bool": {"must": []}},
                "post_filter": {"bool": {"must": []}},
                "size": PAGE,
                "from": offset,
                # The UI's own sort ties on an empty query, which would repeat and skip postings;
                # `id` is unique, so the order is total.
                "sort": [{"id": "asc"}],
                "lang": "zz",
                "localeSelector": {},
                "sm": {"query": "", "lang": "zz"},
                "_source": FIELDS,
            }
            hits = (await http.post_json(SEARCH.format(host=task.board), body)).get("hits") or {}
            return [h.get("_source") or {} for h in hits.get("hits") or []], (
                hits.get("total") or {}
            ).get("value")

        async for items in paged(fetch, PAGE, start_page):
            yield [s for p in items if (s := self.stub(p))]

    def stub(self, p: dict[str, Any]) -> JobStub | None:
        title = " ".join((p.get("title") or "").split())
        body = description(p)
        if not p.get("field_text_01") or not title or not body:
            return None
        url = JOB.format(id=p["field_text_01"])
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="IBM",
            location=location(p.get("field_keyword_19") or "", p.get("field_keyword_05") or ""),
            description=body,
            posted_at=from_iso(p.get("dcdate")),
            ats=self.name,
            apply_url=url,
            remote=mode(p.get("field_keyword_17")),
            extra={
                "id": str(p["field_text_01"]),
                "level": p.get("field_keyword_18"),
                "area": p.get("field_keyword_08"),
                "entity": p.get("field_keyword_20"),
            },
        )
