"""Trakstar Hire (formerly Recruiterbox, {board}.hire.trakstar.com): the public RSS job feed lists
every open position with its body inline. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from lxml import etree
from lxml.etree import _Element

from linkit_all.sources.ats._f13 import get_page, name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

FEED = "https://{board}.hire.trakstar.com/jobfeeds/{board}"


def _posted(raw: str | None) -> datetime | None:
    try:
        dt = parsedate_to_datetime(raw) if raw else None
    except (TypeError, ValueError):
        return None
    return dt.astimezone(UTC).replace(tzinfo=None) if dt and dt.tzinfo else dt


def _fields(item: _Element) -> dict[str, str]:
    """The item's child elements by local name (the `job:` namespace is matched by name, so a
    feed that spells its URI with http instead of https still reads)."""
    return {
        etree.QName(c).localname: (c.text or "").strip() for c in item if isinstance(c.tag, str)
    }


class Trakstar(Source):
    """The board is the tenant subdomain: `cheesecakelabs` for cheesecakelabs.hire.trakstar.com."""

    name = "trakstar"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([\w-]+)\.hire\.trakstar\.com", re.I),)
    cdx_hosts = ("*.hire.trakstar.com",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # one feed holds the whole board
            return
        resp = await get_page(http, FEED.format(board=task.board.lower()))
        root = etree.fromstring(resp.content, etree.XMLParser(resolve_entities=False))
        title = (root.findtext("channel/title") or "").strip().removesuffix(" Jobs").strip()
        company = title or name_from_slug(task.board)
        stubs = []
        for item in root.iterfind("channel/item"):
            f = _fields(item)
            link = f.get("link", "").replace("http://", "https://", 1)
            if not link or not f.get("title"):
                continue
            location = ", ".join(
                f[k] for k in ("locationCity", "locationState", "locationCountry") if f.get(k)
            )
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link,
                    title=" ".join(f["title"].split()),
                    company=company,
                    location=location,
                    description=strip_html(f.get("description", ""), escaped=True),
                    posted_at=_posted(f.get("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote=remote_from_text(f.get("locationCity")),
                    extra={
                        "board": task.board,
                        "id": link.rstrip("/").rsplit("/", 1)[-1],
                        "employment": f.get("positionType"),
                    },
                )
            )
        yield stubs
