"""Profession.hu, Hungary's biggest job board: only the platform's two IT category sitemaps are
read (about 770 postings); each posting page carries a JobPosting block, the body sections and a
work-mode badge. Logic adapted from freehire (MIT)."""

import html
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx
from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.core.search import SearchConfig
from linkit_all.sources.aggregators._f22 import feed_task
from linkit_all.sources.ats._f13 import sitemap_locs
from linkit_all.sources.ats._f16 import GONE, ld_stub
from linkit_all.sources.base import JobStub, Remote, Source, Task
from linkit_all.sources.boards._f32 import posting_pages, sitemap_urls
from linkit_all.sources.common import strip_html
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings

INDEX = "https://www.profession.hu/sitemap-listings-index-hu.xml"
IT_CATEGORIES = ("itdev", "itops")  # the other 21 categories are general-population boards
SECTIONS = ("tasks", "requirements", "other", "offer", "workplace_extras")
# The server cuts a reused connection short, so every request asks for its own.
CLOSE = {"Connection": "close"}
_ID = re.compile(r"/allas/[^/]+-(\d+)(?:/|$)")
_CATEGORY = re.compile(r"/sitemap-listings-([a-z0-9-]+)-hu\.xml$")
_BADGES: dict[str, Remote | None] = {"Hibrid": "hybrid", "Távmunka / Remote": "remote"}
_DIGITS = re.compile(r"\d+")  # postal codes and street numbers stop a location lookup


async def _get(http: Http, url: str) -> str | None:
    """The page text; None when it is gone or unreadable (one bad posting never stops the run)."""
    await http.allowed(url)
    try:
        resp = await http.get(url, headers=CLOSE)
        if resp.status_code in (404, 410):
            return None
        resp.raise_for_status()
    except GONE:
        return None
    return resp.text


def place(address_line: str) -> tuple[Remote, str]:
    """(work mode, place) from the address line: "<badge> • <address>", the badge being optional.
    Only the badge tells a hybrid posting from a remote one."""
    line = " ".join(address_line.split())
    badge, sep, rest = line.partition("•")
    badge, rest = badge.strip(), rest.strip()
    if badge in _BADGES or badge == "Országos lefedettség":  # "nationwide": names no place
        mode: Remote = _BADGES.get(badge) or "onsite"
        return mode, " ".join(_DIGITS.sub(" ", rest if sep else "").split())
    return "onsite", " ".join(_DIGITS.sub(" ", line).split())


def _heading(section: LexborNode) -> str:
    """The title of the box that holds a body section, e.g. "Feladatok"."""
    box = section.parent
    while box is not None and "box-container" not in (box.attributes.get("class") or ""):
        box = box.parent
    h2 = box.css_first("h2") if box is not None else None
    return " ".join(h2.text(deep=True).split()) if h2 is not None else ""


def body(doc: LexborHTMLParser) -> str:
    """The employer's own sections, under their headings. The ld+json description holds the same
    text with its lists flattened into one paragraph, which is why it is not read."""
    parts = []
    for sid in SECTIONS:
        node = doc.css_first(f"#{sid}")
        inner = (node.inner_html or "").strip() if node is not None else ""
        if node is not None and inner:
            head = _heading(node)
            parts.append((f"<h3>{html.escape(head)}</h3>" if head else "") + inner)
    return strip_html("".join(parts))


class Profession(Source):
    name = "profession"
    kind = "board"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return feed_task(self.name, cfg)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        await http.allowed(INDEX)
        resp = await http.get(INDEX, headers=CLOSE)
        resp.raise_for_status()
        subs = [
            u
            for u in sitemap_locs(resp.text)
            if (m := _CATEGORY.search(u)) and m[1] in IT_CATEGORIES
        ]
        texts = []
        for sub in subs:
            r = await http.get(sub, headers=CLOSE)
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError:
                continue  # a category the platform dropped
            texts.append(r.text)
        urls = sitemap_urls("".join(texts), lambda u: bool(_ID.search(u)))

        async def build(url: str) -> JobStub | None:
            text = await _get(http, url)
            postings = job_postings(text) if text else []
            if not text or not postings or not (m := _ID.search(url)):
                return None  # a taken-down posting answers 200 with a category listing
            doc = LexborHTMLParser(text)
            stub = ld_stub(postings[0], source=self.name, url=url, company="", extra={"id": m[1]})
            text_body = body(doc)
            if stub is None or not stub.company or not text_body:
                return None
            line = doc.css_first(".address-data")
            mode, where = place(line.text(deep=True) if line is not None else "")
            update: dict[str, Any] = {
                "description": text_body,
                "remote": mode,
                "location": where or stub.location,
            }
            return stub.model_copy(update=update)

        async for page in posting_pages(urls, start_page, task.limit, build):
            yield page
