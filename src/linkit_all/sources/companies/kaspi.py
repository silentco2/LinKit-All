"""Kaspi.kz's career site (job.kaspi.kz): a server-rendered Nuxt site. The vacancy sitemap lists the
postings and each page carries a schema.org JobPosting, thin and partly filler (the locality is
"KZ"), so the city, salary and schedule come from the page header, where the site shows them. A
single-company plugin, not an ATS. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator

from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f13 import fetch_all, get_page, sitemap_locs
from linkit_all.sources.ats._f15 import safe_date
from linkit_all.sources.ats._f17 import text_of
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.companies._f42 import remote_ru
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

HOST = "job.kaspi.kz"
SITEMAP = "https://{host}/sitemap/vacancies.xml"
CHUNK = 20
_HEAD = "vacancy-single__head__content__"
_URL = re.compile(r"^https://job\.kaspi\.kz/vacancy/([^/]+)/?$")  # /respond below it is a form
_OFFICE = re.compile(r"\s*\([^)]*\)\s*$")  # "(Головной офис)", the head-office note: no place
# An optional "от" (from) / "до" (up to), one amount, an optional tenge sign. Anything else (a
# range, a word, another currency) yields nothing rather than a guess.
_SALARY = re.compile(r"(?i)^(от|до)?\s*(\d[\d\s.]*\d|\d)\s*(тенге|тг|₸)?$")


def salary(label: str) -> tuple[int | None, int | None]:
    """(min, max) tenge per month from "от 800 000 тенге" (a floor), "до ..." (a ceiling) or a
    bare figure (exact)."""
    m = _SALARY.match(label.strip())
    amount = int(re.sub(r"\D", "", m[2])) if m else 0
    if not amount:
        return None, None
    word = (m[1] or "").lower() if m else ""
    return (None if word == "до" else amount), (None if word == "от" else amount)


def parse_vacancy(html: str, url: str) -> JobStub | None:
    m, postings = _URL.match(url), job_postings(html)
    if not m or not postings:
        return None
    p, tree = postings[0], LexborHTMLParser(html)
    cities = text_of(tree.css_first(f'[class~="{_HEAD}salary__cities"]'))
    location = _OFFICE.sub("", cities)
    low, high = salary(text_of(tree.css_first(f'[class~="{_HEAD}salary__label"]')))
    labels = [text_of(n) for n in tree.css(f'[class~="{_HEAD}filter-items__label"]')]
    return JobStub(
        source="kaspi",
        url=url,
        title=" ".join(str(p.get("title") or "").split()),
        company="Kaspi.kz",  # hiringOrganization only repeats it
        location=location,
        description=strip_html(p.get("description") or "", escaped=True),  # entity-escaped HTML
        posted_at=safe_date(p.get("datePosted")),  # zone-less, and UTC
        ats="kaspi",
        apply_url=url,
        remote=remote_ru(location, p.get("title")),
        salary_min=low,
        salary_max=high,
        salary_currency="KZT" if low or high else None,
        salary_interval="month" if low or high else None,
        extra={"id": m[1], "schedule": labels},
    )


class Kaspi(Source):
    name = "kaspi"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "kaspi:vacancies", board=HOST)]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        xml = (await get_page(http, SITEMAP.format(host=task.board))).text
        urls = [u for u in sitemap_locs(xml) if _URL.match(u)]
        for i in range(start_page * CHUNK, len(urls), CHUNK):
            stubs = await fetch_all(http, urls[i : i + CHUNK], parse_vacancy)
            yield [s for s in stubs if s.title]
