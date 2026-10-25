"""WeRecruit career sites (careers.werecruit.io/<locale>/<tenant>): the listing page embeds every
open offer as `window.allOffers`; each offer's own page carries the body.
Logic adapted from freehire (MIT)."""

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from selectolax.lexbor import LexborHTMLParser

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, hydrate, page_text
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug, when
from linkit_all.sources.text import html_to_text

BASE = "https://careers.werecruit.io"
CHUNK = 20  # offers per yielded page: their detail fetches run together
_OFFERS = re.compile(r"window\.allOffers\s*=\s*")


def split_board(board: str) -> tuple[str, str]:
    """ "locale/tenant". The locale matters: a tenant set up for one locale answers every other
    with an empty list, not an error."""
    parts = board.strip("/").split("/")
    if len(parts) != 2 or not all(parts):
        raise ValueError(f'werecruit: board {board!r} must be "<locale>/<tenant>"')
    return parts[0], parts[1]


def offers_of(page: str) -> list[dict[str, Any]]:
    """The offers array that follows `window.allOffers =`; none when the page has no such
    assignment (an unconfigured locale)."""
    m = _OFFERS.search(page)
    if m is None:
        return []
    offers, _ = json.JSONDecoder().raw_decode(
        page, m.end()
    )  # reads the one array, stops at its end
    return [o for o in offers if o.get("Id") and o.get("Url")]


class WeRecruit(Source):
    """The board is `<locale>/<tenant>`, as in careers.werecruit.io/en/idiap."""

    name = "werecruit"
    kind = "ats"
    url_patterns = (re.compile(r"careers\.werecruit\.io/([a-z]{2}(?:-[a-z]{2})?)/([\w-]+)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        locale, tenant = split_board(task.board)
        offers = offers_of((await get_page(http, f"{BASE}/{locale}/{tenant}")).text)

        async def build(o: dict[str, Any]) -> JobStub | None:
            page = await page_text(http, o["Url"])
            if page is None:  # not stored without its body: the next run retries it
                return None
            node = LexborHTMLParser(page).css_first("div.description")  # not div.description-blocks
            return self.stub(o, html_to_text(node.html or "") if node else "", task.board, tenant)

        async for stubs in hydrate(offers, start_page, build, CHUNK):
            yield stubs

    @staticmethod
    def stub(o: dict[str, Any], description: str, board: str, tenant: str) -> JobStub:
        location = ", ".join(p for p in (o.get("Address_City"), o.get("Address_Region")) if p)
        return JobStub(
            source="werecruit",
            url=o["Url"],
            title=" ".join((o.get("TitleTranslated") or "").split()),
            company=name_from_slug(tenant),
            location=location,
            description=description,
            posted_at=when(o.get("PublicationStartDate")),
            ats="werecruit",
            apply_url=o["Url"],
            remote=remote_from_text(location),
            extra={
                "board": board,
                "id": o["Id"],
                "employment": o.get("TimeTranslated"),
                "country": o.get("Address_State"),  # an ISO country code despite the name
            },
        )
