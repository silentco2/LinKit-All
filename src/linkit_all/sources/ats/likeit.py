"""Likeit (Saarni Likeit Oy, Finland): each tenant publishes an RSS feed of its open adverts with
the HTML body inline. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlsplit

from lxml import etree
from lxml.etree import _Element

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import get_page, strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug, when

FEED = "https://{board}.likeit.fi/jsp/duuni/AdvertRss.jsp"
_DC_DATE = "{http://purl.org/dc/elements/1.1/}date"


def _posted(item: _Element) -> datetime | None:
    """The RFC 3339 dc:date when the item has one, else its RFC 822 pubDate."""
    if (stamp := when(item.findtext(_DC_DATE))) or not (raw := item.findtext("pubDate")):
        return stamp
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


class Likeit(Source):
    """The board is the tenant subdomain: `<board>.likeit.fi`."""

    name = "likeit"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([\w-]+)\.likeit\.fi", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one feed holds the whole board
            return
        resp = await get_page(http, FEED.format(board=task.board))
        root = etree.fromstring(resp.content, etree.XMLParser(resolve_entities=False))
        company = name_from_slug(task.board)
        stubs = []
        for item in root.iterfind("channel/item"):
            link = (item.findtext("link") or "").strip()
            ids = parse_qs(urlsplit(link).query).get("id")  # the channel's list link has none
            title = " ".join((item.findtext("title") or "").split())
            if not ids or not title:
                continue
            location = (item.findtext("category") or "").strip()  # "region, city", not a category
            stubs.append(
                JobStub(
                    source="likeit",
                    url=link,
                    title=title,
                    company=company,
                    location=location,
                    description=strip_html(item.findtext("description") or ""),
                    posted_at=_posted(item),
                    ats="likeit",
                    apply_url=link,
                    remote=remote_from_text(location),
                    extra={"board": task.board, "id": ids[0]},
                )
            )
        yield stubs
