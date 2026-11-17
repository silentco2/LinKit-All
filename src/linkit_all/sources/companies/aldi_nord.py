"""ALDI Nord group careers on its country sites (www.aldi-nord.de, .nl, .be, .lu, .fr, .es, .pt,
.pl): every site's front calls the same keyless job search API, where the `locale` alone picks
the country's postings. Its `page` is cumulative (page N returns the first 10*N rows), so each
locale costs two requests: page 1 for the total, then the page that covers it.
Logic adapted from career-ops (MIT)."""

from collections.abc import AsyncIterator
from math import ceil
from typing import Any
from urllib.parse import quote

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import clean, safe_date

PAGE = 10
MAX_PAGES = 1000
# host: {locale: posting page path}
SITES: dict[str, dict[str, str]] = {
    "www.aldi-nord.de": {"de-DE": "/karriere/detail/"},
    "www.aldi.nl": {"nl-NL": "/carriere/detail/"},
    "www.aldi.be": {"nl-BE": "/jobs/detail/", "fr-BE": "/fr/jobs/detail/"},
    "www.aldi.lu": {"fr-LU": "/jobs/detail/"},
    "www.aldi.fr": {"fr-FR": "/carriere/detail/"},
    "www.aldi.es": {"es-ES": "/empleo/detail/"},
    "www.aldi.pt": {"pt-PT": "/carreira/detail/"},
    "www.aldi.pl": {"pl-PL": "/praca/detail/"},
}


def place(locations: Any) -> str:
    """ "Essen / Dortmund, Deutschland"; one "City, Country" per place when countries differ."""
    found = (
        (clean(loc.get("city")), clean(loc.get("country")))
        for loc in (locations if isinstance(locations, list) else [])
        if isinstance(loc, dict)
    )
    rows = list(dict.fromkeys(r for r in found if r != ("", "")))
    countries = list(dict.fromkeys(c for _, c in rows if c))
    if len(countries) <= 1:
        cities = " / ".join(dict.fromkeys(c for c, _ in rows if c))
        return ", ".join(x for x in (cities, countries[0] if countries else "") if x)
    return "; ".join(", ".join(x for x in r if x) for r in rows)


class AldiNord(Source):
    name = "aldi-nord"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [
            Task(self.name, f"{self.name}:{locale}", board=host, location=locale)
            for host, locales in SITES.items()
            for locale in locales
        ]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # two requests cover a whole locale
            return
        host, locale = task.board, task.location
        url = f"https://{host}/api/job/hr/query"

        async def query(page: int) -> dict[str, Any]:
            body = {
                "careerLevelIds": [],
                "jobTypeParams": {"jobTypeIds": []},
                "jobCategoryIds": [],
                "title": "",
                "location": {"searchPhrase": ""},
                "page": page,
                "locale": locale,
            }
            data = await http.post_json(url, body)
            if not isinstance(data, dict) or not isinstance(data.get("results"), list):
                raise ValueError("aldi-nord: the response carries no results array")
            return data

        data = await query(1)
        total = data.get("total")
        if data.get("hasNextPage") and isinstance(total, int):
            data = await query(min(MAX_PAGES, ceil(total / PAGE)))
        stubs = [
            s for r in data["results"] if isinstance(r, dict) and (s := self.stub(r, host, locale))
        ]
        if stubs:
            yield list({s.url: s for s in stubs}.values())

    def stub(self, r: dict[str, Any], host: str, locale: str) -> JobStub | None:
        title, slug = clean(r.get("title")), str(r.get("slugTitle") or "").strip()
        jid = str(r.get("postingId") or "").strip()
        if not (title and slug and jid):
            return None
        url = (
            f"https://{host}{SITES[host][locale]}{quote(slug, safe='')}-{quote(jid, safe='')}.html"
        )
        where = place(r.get("locations"))
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company=clean(r.get("companyName")) or "ALDI Nord",
            location=where,
            posted_at=safe_date(r.get("onlineFrom")),
            ats=self.name,
            apply_url=url,
            remote=remote_from_text(where, title),
            extra={"id": jid, "locale": locale},
        )
