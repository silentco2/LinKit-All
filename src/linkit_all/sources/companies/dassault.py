"""Dassault Systemes careers (www.3ds.com/careers/jobs): their Taleo section is not public, so the
postings are read from the site's own Exalead card search (English career cards), which carries
each posting's body. Single-company plugin. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import urlsplit

from lxml import etree

from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, paged, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import ats_of
from linkit_all.sources.tasks import fresh

# Both refinements matter: without the content-type facet the index is the whole site's cards,
# without the language facet every posting comes back once per language. hf is the page size.
SEARCH = (
    "https://www.3ds.com/apisearch/card_search_api?lang=en"
    "&r=f/card_content_type/career&r=f/card_content_categories_facet/cards%20language/en"
    "&hf={size}&start={start}"
)
PAGE = 100
NS = {"e": "exa:com.exalead.search.v10"}
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
# "Category/X Type/Y Country/Z City/W Products/V Year/U": values hold spaces and commas, so the
# split anchors on the fixed order of the six labels.
_CATEGORIES = re.compile(r"^Category/.* Type/.* Country/(.*) City/(.*) Products/.* Year/.*$")


def parse_cards(xml: bytes) -> tuple[list[dict[str, str]], int | None]:
    """(cards as {meta name: first value}, the stated total number of hits)."""
    root = etree.fromstring(xml, _PARSER)
    cards = [
        {
            m.get("name", ""): (m.findtext("e:MetaString", default="", namespaces=NS) or "").strip()
            for m in hit.iterfind("e:metas/e:Meta", NS)
        }
        for hit in root.iterfind("e:hits/e:Hit", NS)
    ]
    nhits = root.get("nhits")
    return cards, int(nhits) if nhits and nhits.isdigit() else None


def location_of(card: dict[str, str]) -> str:
    """ "City, Country". The City facet repeats the country and a region code before the city
    ("India, MH, Pune"), so the city is its last comma-separated part."""
    m = _CATEGORIES.match(card.get("content_categories", ""))
    if not m:
        return card.get("content_info_2_value", "")
    country, city = m[1].strip(), m[2].rsplit(",", 1)[-1].strip()
    if not city or city.lower() == country.lower():
        return country
    return f"{city}, {country}" if country else city


class Dassault(Source):
    name = "dassault"
    kind = "company"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, "dassault:careers")]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        seen: set[str] = set()

        async def fetch(offset: int) -> tuple[list[dict[str, str]], int | None]:
            resp = await get_page(http, SEARCH.format(size=PAGE, start=offset))
            return parse_cards(resp.content)

        async for cards in paged(fetch, PAGE, start_page):
            page = fresh((self.stub(c) for c in cards), seen)
            yield page

    def stub(self, c: dict[str, str]) -> JobStub | None:
        url = c.get("content_cta_1_url", "")
        title = " ".join(c.get("content_title", "").split())
        description = strip_html(c.get("content_summary", ""))
        if urlsplit(url).hostname != "www.3ds.com" or not c.get("card_id") or not title:
            return None
        try:  # "2026/10/14 03:10:27"
            posted = datetime.strptime(c.get("content_start_datetime", ""), "%Y/%m/%d %H:%M:%S")
        except ValueError:
            posted = None
        location = location_of(c)
        return JobStub(
            source=self.name,
            url=url,
            title=title,
            company="Dassault Systèmes",
            location=location,
            description=description,
            posted_at=posted,
            ats=ats_of(url, self.name),
            apply_url=url,
            remote=remote_from_text(title, location),
            extra={"id": c["card_id"]},
        )
