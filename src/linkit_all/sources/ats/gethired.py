"""GetHired (easyapply.co): every tenant publishes its open positions as one RSS feed with the
description inline. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from lxml import etree

from linkit_all.sources.ats._f13 import name_from_slug
from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http

FEED = "https://{board}.easyapply.co/rss"


class GetHired(Source):
    """The board is the tenant subdomain: `<board>.easyapply.co`."""

    name = "gethired"
    kind = "ats"
    url_patterns = (re.compile(r"(?<![\w.-])(?!www\.)([\w-]+)\.easyapply\.co", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:
            return
        url = FEED.format(board=task.board)
        await http.allowed(url)
        resp = await http.get(url)
        if resp.is_redirect or not str(resp.url).startswith(url):  # unknown tenant -> sign-in page
            raise ValueError(f"gethired: no career site for {task.board!r}")
        resp.raise_for_status()
        root = etree.fromstring(resp.content, etree.XMLParser(resolve_entities=False))
        company = root.findtext("channel/title") or name_from_slug(task.board)
        stubs = []
        for item in root.iterfind("channel/item"):
            slug = (item.findtext("guid") or "").partition("/job/")[2].strip("/ ")
            if not slug:
                continue
            location = (item.findtext("category") or "").strip()
            link = f"https://easyapply.co/job/{slug}"
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link,
                    title=(item.findtext("title") or "").strip(),
                    company=company.strip(),
                    location=location,
                    description=strip_html(item.findtext("description") or ""),
                    posted_at=_date(item.findtext("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote=remote_from_text(location),
                    extra={"board": task.board, "id": slug},
                )
            )
        yield stubs


def _date(value: str | None) -> datetime | None:
    try:
        dt = parsedate_to_datetime(value or "")
    except (TypeError, ValueError):
        return None
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt
