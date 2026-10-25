"""Helpers private to the F3.2 board plugins (the underscore keeps it out of the registry)."""

import html
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.entities import html5

from lxml import etree

from linkit_all.sources.ats._f16 import CHUNK
from linkit_all.sources.ats._f17 import hydrate
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

# Hardened: no entity resolution, no network. Feeds are third-party text, so recover from slips.
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=True)
_DECL = re.compile(r"^\s*<\?xml[^>]*\?>")
_NAMED = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
_URL = re.compile(r"<url>(.*?)</url>", re.S | re.I)
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
_LASTMOD = re.compile(r"<lastmod>\s*([^<]+?)\s*</lastmod>", re.I)


def _html_entity(m: re.Match[str]) -> str:
    """Feeds written by some static-site generators carry HTML names ("&rsquo;") outside CDATA,
    which XML rejects; swap them for the character."""
    name = m[1]
    return m[0] if name in _XML_ENTITIES else html5.get(name + ";", m[0])


def feed_items(xml: str) -> list[dict[str, str]]:
    """Each RSS `<item>` as {child tag without namespace: text}. Empty for text that is no feed."""
    text = _NAMED.sub(_html_entity, _DECL.sub("", xml))
    root = etree.fromstring(text.encode("utf-8"), _PARSER)
    if root is None:
        return []
    items = []
    for item in root.iter("item"):
        row: dict[str, str] = {}
        for child in item:
            if isinstance(child.tag, str):
                row.setdefault(
                    etree.QName(child).localname, "".join(str(t) for t in child.itertext()).strip()
                )
        items.append(row)
    return items


def rfc_date(value: str | None) -> datetime | None:
    """An RSS pubDate ("Mon, 10 Aug 2026 16:40:02 +0200") as naive UTC."""
    try:
        dt = parsedate_to_datetime((value or "").strip())
    except (TypeError, ValueError):
        return None
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def ats_of(apply_url: str | None, board: str) -> str:
    """The ATS behind the employer's own apply link, else the board's own name."""
    hit = detect(apply_url) if apply_url else None
    return hit[0] if hit else board


def sitemap_urls(xml: str, keep: Callable[[str], bool]) -> list[str]:
    """The `<loc>`s of a urlset that pass `keep`, newest `<lastmod>` first, without repeats."""
    rows = []
    for block in _URL.findall(xml):
        loc, mod = _LOC.search(block), _LASTMOD.search(block)
        if loc and keep(url := html.unescape(loc[1])):
            rows.append((mod[1] if mod else "", url))
    rows.sort(key=lambda r: r[0], reverse=True)  # stable: sitemap order among equal dates
    return list(dict.fromkeys(url for _, url in rows))


async def posting_pages(
    urls: list[str],
    start_page: int,
    limit: int,
    build: Callable[[str], Awaitable[JobStub | None]],
) -> AsyncIterator[list[JobStub]]:
    """Build a stub from each of the first `limit` URLs, CHUNK at a time (one page per chunk).
    Empty pages are yielded too, so the checkpoint's page number stays the chunk number."""
    async for page in hydrate(urls[:limit], start_page, build, CHUNK):
        yield page


async def sitemap_text(http: Http, url: str) -> str:
    """A sitemap's text; HTTP errors raise."""
    await http.allowed(url)
    resp = await http.get(url)
    resp.raise_for_status()
    return resp.text


def body_text(raw: str) -> str:
    """A feed's description as text. Some feeds escape their markup twice ("&lt;p&gt;" with no
    "<" at all), so that case is unescaped once before the HTML is read."""
    return html_to_text(raw, escaped="<" not in raw and "&lt;" in raw)
