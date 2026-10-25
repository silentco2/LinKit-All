"""Oracle Taleo Business Edition career sites (board = "ORG:cws", e.g. "AMERINC:52"): every career
site publishes its whole listing as one RSS feed with the HTML body inline, reached through the
platform's dispatcher so the org's pod does not matter. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlencode, urlsplit

from lxml import etree

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.parsing import name_from_slug
from linkit_all.sources.text import html_to_text

_NS = "{urn:TBERss}"
_ORG = re.compile(r"^[A-Z0-9_]+$")
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
# Where the platform sends a board that is gone: unknown org, deactivated org, unknown site.
_GONE = ("/dispatcher/login.jsp", "/rssErrMsg.jsp")


def feed_url(board: str) -> str:
    """The RSS feed of "ORG:cws" (or the detector's "ORG/cws"), via the platform dispatcher."""
    org, _, cws = board.replace("/", ":").partition(":")
    org = org.upper()
    if not (_ORG.match(org) and cws.isdigit()):
        raise Unsupported(f'taleobe: board "{board}" must be "ORG:cws"')
    feed = "https://tbe.taleo.net/ats/servlet/Rss?" + urlencode({"org": org, "cws": cws})
    query = urlencode({"org": org, "act": "redirectOrg", "redirectUrl": feed})
    return f"https://tbe.taleo.net/dispatcher/servlet/DispatcherServlet?{query}"


def _pub_date(value: str | None) -> datetime | None:
    """RFC 2822 ("Tue, 20 Oct 2026 13:12:18 GMT") as naive UTC; None for anything else."""
    try:
        dt = parsedate_to_datetime((value or "").strip())
    except (TypeError, ValueError):
        return None
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


class TaleoBE(Source):
    name = "taleobe"
    kind = "ats"
    # org and cws are both query parameters of every TBE URL; the detector joins them with "/"
    url_patterns = (
        re.compile(r"\.tbe\.taleo\.net/[^\s\"']*?\borg=([A-Za-z0-9_]+)&(?:amp;)?cws=(\d+)", re.I),
    )
    cdx_hosts = ("*.tbe.taleo.net/*",)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        if start_page > 0:  # the feed is not paged
            return
        resp = await http.get(feed_url(task.board))
        final = urlsplit(str(resp.url)).path
        if final.endswith(_GONE) or final.startswith("/errorpages/"):
            raise Unsupported(f"taleobe: board {task.board} no longer exists")
        resp.raise_for_status()
        channel = etree.fromstring(resp.content, _PARSER)
        stubs = []
        for item in channel.iterfind("channel/item"):
            link = (item.findtext("link") or "").strip().replace("http://", "https://", 1)
            req = (item.findtext(f"{_NS}reqId") or "").strip() or (
                parse_qs(urlsplit(link).query).get("rid", [""])[0]
            )
            title = " ".join((item.findtext("title") or "").split())
            if not (req and link and title):
                continue
            city = (item.findtext(f"{_NS}locationCity") or "").strip()
            state = (item.findtext(f"{_NS}locationState") or "").strip()
            location = (item.findtext(f"{_NS}location") or "").strip() or ", ".join(
                p for p in (city, state) if p
            )
            body = item.findtext(f"{_NS}html-description") or item.findtext("description") or ""
            stubs.append(
                JobStub(
                    source=self.name,
                    url=link,
                    title=title,
                    company=name_from_slug(task.board.replace("/", ":").split(":")[0]),
                    location=location,
                    description=html_to_text(body),
                    posted_at=_pub_date(item.findtext("pubDate")),
                    ats=self.name,
                    apply_url=link,
                    remote=remote_from_text(location),
                    extra={"board": task.board, "id": req},
                )
            )
        yield stubs
