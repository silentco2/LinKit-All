"""Avature career sites (e.g. ea.avature.net); the board is the career-site host. Postings come
from the host's sitemaps and each page. Logic adapted from freehire (MIT)."""

import re
from collections.abc import AsyncIterator
from urllib.parse import urlsplit

from selectolax.lexbor import LexborHTMLParser
from selectolax.lexbor import LexborNode as Node

from linkit_all.sources.base import JobStub, Remote, Source, Task, from_iso
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http
from linkit_all.sources.text import html_to_text

PAGE = 10  # job pages per checkpoint
FIELD = "article__content__view__field"
_LOCALE = re.compile(r"/[a-z]{2}_[A-Z]{2}/")
_JOB_ID = re.compile(r"/JobDetail/[^/]+/(\d+)/?$")
_SITEMAPS = re.compile(r"<sitemap>.*?<loc>\s*([^<]+?)\s*</loc>", re.S)
_URLS = re.compile(r"<url>(.*?)</url>", re.S)
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>")
_LASTMOD = re.compile(r"<lastmod>\s*([^<]+?)\s*</lastmod>")
_ROBOTS_MAP = re.compile(r"^\s*Sitemap:\s*(\S+)", re.I | re.M)
_PROSE = "p, ul, ol, li, h1, h2, h3, h4, h5, h6, table"


def work_mode(value: str) -> Remote | None:
    v = value.lower()
    if "remote" in v:
        return "remote"
    if "hybrid" in v:
        return "hybrid"
    if any(k in v for k in ("on-site", "on site", "onsite", "in-office", "in office")):
        return "onsite"
    return None


def field_value(tree: LexborHTMLParser, label: str) -> str:
    """Value of the sidebar field (label/value pair) with this label."""
    for field in tree.css(f"div.{FIELD}"):
        lab, val = field.css_first(f".{FIELD}__label"), field.css_first(f".{FIELD}__value")
        if lab and val and lab.text().strip().lower() == label.lower():
            return val.text().strip()
    return ""


def labeled_value(tree: LexborHTMLParser, label: str) -> str:
    """An inline "<strong>Label</strong>: value" field (how Locations is shown)."""
    for val in tree.css(f".{FIELD}__value"):
        strong = val.css_first("strong")
        if strong is None or strong.text().strip().lower() != label.lower():
            continue
        text = val.text().split("\xa0", 1)[0]  # a hidden list of every location follows a nbsp
        return text.strip().removeprefix(strong.text().strip()).lstrip(": \xa0").strip()
    return ""


def description(tree: LexborHTMLParser) -> str:
    """The richest field value that has block markup (the ad body); else the richest value."""
    values: list[Node] = tree.css(f".{FIELD}__value")
    prose = [v for v in values if v.css_first(_PROSE) is not None]
    best = max(prose or values, key=lambda v: len(v.text()), default=None)
    return html_to_text(best.html or "") if best else ""


def meta(tree: LexborHTMLParser, prop: str) -> str:
    node = tree.css_first(f'meta[property="{prop}"]')
    return (node.attributes.get("content") or "").strip() if node else ""


class Avature(Source):
    name = "avature"
    kind = "ats"
    url_patterns = (re.compile(r"https?://([\w-]+\.avature\.net)(?:/|\b)", re.I),)

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        board = task.board.lower().strip("/")
        entries = await self._postings(http, board)
        for page in range(start_page, (len(entries) + PAGE - 1) // PAGE):
            stubs = []
            for url, lastmod in entries[page * PAGE : (page + 1) * PAGE]:
                if not await http.allowed(url):
                    continue
                resp = await http.get(url)
                if resp.status_code in (404, 410):
                    continue
                resp.raise_for_status()
                if stub := self.parse_page(resp.text, url, board, lastmod):
                    stubs.append(stub)
            yield stubs

    @staticmethod
    def parse_page(html: str, url: str, board: str, lastmod: str | None) -> JobStub | None:
        tree = LexborHTMLParser(html)
        job_id = _JOB_ID.search(url)
        title, body = meta(tree, "og:title"), description(tree)
        if job_id is None or not title or not body:  # an unrendered page: skip, don't store a husk
            return None
        return JobStub(
            source="avature",
            url=url,
            title=title,
            company=meta(tree, "og:site_name") or board.split(".")[0].replace("-", " ").title(),
            location=labeled_value(tree, "Locations"),
            description=body,
            posted_at=from_iso(lastmod),
            ats="avature",
            apply_url=url,
            remote=work_mode(field_value(tree, "Work Model")),
            extra={"board": board, "id": job_id[1]},
        )

    async def _postings(self, http: Http, board: str) -> list[tuple[str, str | None]]:
        """(url, lastmod) of every JobDetail page. /careers/ is tried first; a tenant that names
        its portal otherwise advertises it as a `Sitemap:` line in robots.txt."""
        index = f"https://{board}/careers/sitemap_index.xml"
        entries = await self._job_locs(http, index)
        if not entries:
            robots = f"https://{board}/robots.txt"
            if await http.allowed(robots):
                resp = await http.get(robots)
                tried = {index}
                for url in _ROBOTS_MAP.findall(resp.text if resp.status_code < 400 else ""):
                    if urlsplit(url).netloc.lower() != board or url in tried:
                        continue  # another host's portal, or one already tried
                    tried.add(url)
                    if entries := await self._job_locs(http, url):
                        break
        if not entries:
            raise Unsupported(f"no JobDetail postings in the sitemaps of {board}")
        return entries

    async def _job_locs(self, http: Http, index_url: str) -> list[tuple[str, str | None]]:
        text = await self._xml(http, index_url)
        subs = _SITEMAPS.findall(text or "")
        # Locales list the same postings: prefer en_US. A locale split without en_US yields
        # nothing rather than a guess; no split at all uses the one sub-sitemap.
        pick = next((s for s in subs if "/en_US/" in s), None)
        if pick is None and not any(_LOCALE.search(s) for s in subs) and len(subs) == 1:
            pick = subs[0]
        listing = await self._xml(http, pick) if pick else None
        out = []
        for block in _URLS.findall(listing or ""):
            loc, mod = _LOC.search(block), _LASTMOD.search(block)
            if loc and "/JobDetail/" in loc[1]:
                out.append((loc[1], mod[1] if mod else None))
        return out

    @staticmethod
    async def _xml(http: Http, url: str) -> str | None:
        if not await http.allowed(url):
            raise Unsupported(f"robots.txt does not allow fetching {url}")
        resp = await http.get(url)
        if resp.status_code in (404, 410):
            return None
        resp.raise_for_status()
        return resp.text
