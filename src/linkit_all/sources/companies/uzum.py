"""Uzum's careers site (people.uzum.com): the sitemap lists the vacancies and each page's Next.js
flight carries the posting. Uzum is a holding (Market, Bank, Nasiya, Tezkor), so a vacancy's
business unit is its employer. The sitemap lists every vacancy under /career/ru/ and /career/uz/;
only the Russian copy is read (its "_en" fields hold Uzbek text). A single-company plugin, not an
ATS. Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f13 import get_page, sitemap_locs
from linkit_all.sources.ats._f16 import CHUNK, page_text
from linkit_all.sources.ats._f17 import hydrate
from linkit_all.sources.ats.deel import bracket_slice, decode_flight, text_rows
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

SITEMAP = "https://people.uzum.com/sitemap.xml"
_URL = re.compile(r"^https://people\.uzum\.com/career/ru/vacancies/(\d+)/?$")
_MODES: dict[str, Remote] = {"office": "onsite", "hybrid": "hybrid", "remote": "remote"}


def body_html(body: str) -> str:
    """The posting body: a page-builder document whose text components hold the HTML (anything
    else is taken to be the HTML itself)."""
    if not body.lstrip().startswith("{"):
        return body
    try:
        parts = json.loads(body).get("components") or []
    except ValueError:
        return body
    return "".join(
        (c.get("value") or {}).get("body") or "" for c in parts if c.get("type") == "text"
    )


def parse_vacancy(page: str, url: str) -> JobStub | None:
    m = _URL.match(url)
    if not m:
        return None
    try:
        flight = decode_flight(page)
    except ValueError:
        return None
    # Keyed on the page's own id: the apply form further down names the prop as a back-reference.
    raw = bracket_slice(flight, f'"vacancy":{{"id":{m[1]},', "{", "}")
    try:
        v: dict[str, Any] = json.loads(raw) if raw else {}
    except ValueError:
        v = {}
    title = " ".join(str(v.get("title_ru") or v.get("title_en") or "").split())
    if not title or v.get("disabled") or v.get("status") != "Published":
        return None
    body = str(v.get("body_ru") or "")
    if body.startswith("$"):  # a reference to a text row of the flight
        body = text_rows(flight).get(body[1:], "")

    def label(key: str) -> str:
        return str(((v.get(key) or {}).get("labels") or {}).get("ru") or "").strip()

    city = label("city")
    try:
        posted = datetime.strptime(str(v.get("publication_date")), "%m/%d/%Y")
    except ValueError:
        posted = None
    return JobStub(
        source="uzum",
        ats="uzum",
        url=url,
        title=title,
        company=label("business_unit") or "Uzum",
        # Every city the site lists is in Uzbekistan.
        location=f"{city}, Узбекистан" if city else "Узбекистан",
        description=strip_html(body_html(body)),
        posted_at=posted,
        apply_url=url,
        remote=_MODES.get((v.get("work_mode") or {}).get("work_mode_key") or ""),
        extra={"id": m[1]},
    )


class Uzum(Source):
    name = "uzum"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "uzum:careers", board="people.uzum.com")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        xml = (await get_page(http, SITEMAP)).text
        urls = list(dict.fromkeys(u.rstrip("/") for u in sitemap_locs(xml) if _URL.match(u)))

        async def build(url: str) -> JobStub | None:
            page = await page_text(http, url)  # a page that 404s is a withdrawn vacancy
            return parse_vacancy(page, url) if page else None

        async for page in hydrate(urls, start_page, build, CHUNK):
            yield page
