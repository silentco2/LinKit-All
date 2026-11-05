"""Find LinkedIn hiring posts through Google (`site:linkedin.com/posts`), with no LinkedIn login.

Google runs in real installed Chrome (core/chrome.py) on its own persistent profile, `google`, so
its cookies build up like a person's browser. Per keyword at most MAX_PAGES result pages, at a
reading pace. Google's result links are opaque redirects (`/goto?url=...`, seen 2026-10-31); each
is resolved with one request that follows no redirect, so LinkedIn is never loaded in the browser.

A Google check (the `/sorry` reCAPTCHA page) or a cookie-consent page stops the search for the
run: the user solves it in the app browser on the same profile (CLAUDE.md §5.2: the app never
solves or bypasses a check).
"""

import asyncio
import contextlib
import random
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, quote_plus, urljoin, urlsplit

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright
from selectolax.lexbor import LexborHTMLParser

from linkit_all.core.chrome import RunningChrome, open_context
from linkit_all.sources.base import from_epoch_ms

PROFILE = "google"  # Chrome profile name under <data>/browser/
GOOGLE = "https://www.google.com"
MAX_PAGES = 5  # result pages per keyword (10 results each)
TBS = {"day": "qdr:d", "week": "qdr:w"}
# The post id: `.../posts/<slug>-activity-<id>-<4 chars>` (also ugcPost / share ids)
POST = re.compile(r"^/posts/[^/?#]*?-(activity|ugcPost|share)-(\d{15,22})", re.I)

Blocked = Literal["check", "consent"]


class GoogleBlocked(Exception):
    """Google shows a check or a consent page; only the user can get past it."""

    def __init__(self, kind: Blocked) -> None:
        super().__init__(kind)
        self.kind = kind


def search_url(keywords: str, window: Literal["day", "week"], start: int = 0) -> str:
    q = quote_plus(f"site:linkedin.com/posts {keywords.strip()}")
    return f"{GOOGLE}/search?q={q}&tbs={TBS[window]}" + (f"&start={start}" if start else "")


def blocked(url: str, html: str) -> Blocked | None:
    """What stands between us and the results, from the page's URL and HTML (None = results)."""
    parts = urlsplit(url)
    if parts.hostname and parts.hostname.startswith("consent."):
        return "consent"
    if parts.path.startswith("/sorry"):
        return "check"
    # ponytail: no text check, a result snippet can say "unusual traffic" too
    return "check" if 'id="captcha-form"' in html else None


def post_id(url: str) -> tuple[str, str] | None:
    """("activity", "75215...") for a LinkedIn post URL, else None."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not (host == "linkedin.com" or host.endswith(".linkedin.com")):
        return None
    m = POST.match(parts.path)
    return (m.group(1).lower(), m.group(2)) if m else None


def canonical(url: str) -> str:
    """The post URL without query or fragment, on www.linkedin.com."""
    return f"https://www.linkedin.com{urlsplit(url).path}"


def posted_from_id(kind: str, ident: str) -> datetime | None:
    """Activity ids carry their publish time: the top 41 bits are epoch ms (naive UTC)."""
    return from_epoch_ms(int(ident) >> 22) if kind == "activity" else None


def result_links(html: str, base: str = GOOGLE) -> tuple[list[str], bool]:
    """(absolute links of the organic results, is there a next page). A result is an anchor with
    an <h3> inside #search."""
    tree = LexborHTMLParser(html)
    links: dict[str, None] = {}
    for a in tree.css("#search a[href]"):
        if a.css_first("h3") is not None:
            links[urljoin(base, a.attributes.get("href") or "")] = None
    return list(links), tree.css_first("a#pnnext") is not None


def direct_target(link: str) -> str | None:
    """The LinkedIn URL a result link names openly (direct, or `/url?q=`), else None."""
    if post_id(link):
        return link
    parts = urlsplit(link)
    if parts.path in ("/url", "/goto"):
        for key in ("q", "url"):
            for value in parse_qs(parts.query).get(key, []):
                if post_id(value):
                    return value
    return None


Pause = Callable[[float, float], float]


class GoogleSearch:
    """One Chrome on the `google` profile, opened on first use and kept for the run."""

    def __init__(self, profile: Path, headless: bool, pause: Pause = random.uniform) -> None:
        self.profile, self.headless, self._pause = profile, headless, pause
        self._pw: Playwright | None = None
        self._chrome: RunningChrome | None = None
        self._ctx: BrowserContext | None = None

    async def _page(self) -> Page:
        if self._ctx is None:
            self._pw = await async_playwright().start()
            try:
                self._chrome, self._ctx = await open_context(
                    self._pw, self.profile, headless=self.headless
                )
            except BaseException:
                await self.close()
                raise
        return self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()

    async def _sleep(self, low: float, high: float) -> None:
        await asyncio.sleep(self._pause(low, high))  # pacing, not security

    async def post_urls(
        self, keywords: str, window: Literal["day", "week"], max_posts: int
    ) -> list[str]:
        """Canonical post URLs for one keyword, in Google's order. Raises GoogleBlocked."""
        page = await self._page()
        found: dict[str, None] = {}
        for n in range(min(MAX_PAGES, -(-max_posts // 10))):
            if n:
                await self._sleep(6.0, 14.0)  # reading the previous page
            with contextlib.suppress(Exception):  # slow page: judge what arrived
                await page.goto(search_url(keywords, window, 10 * n), wait_until="load")
            html = await page.content()
            if (kind := blocked(page.url, html)) is not None:
                raise GoogleBlocked(kind)
            links, more = result_links(html, page.url)
            for link in links:
                target = direct_target(link) or await self._resolve(link)
                if target is not None:
                    found.setdefault(canonical(target), None)
                if len(found) >= max_posts:
                    return list(found)
            if not more:
                break
        return list(found)

    async def _resolve(self, link: str) -> str | None:
        """Where an opaque Google redirect points, without following it."""
        if urlsplit(link).hostname not in ("www.google.com", "google.com"):
            return None
        if self._ctx is None:
            return None
        await self._sleep(0.8, 2.0)
        try:
            resp = await self._ctx.request.get(link, max_redirects=0, timeout=15000)
        except Exception:
            return None
        target = resp.headers.get("location", "")
        if blocked(target, "") is not None:
            raise GoogleBlocked("check")
        return target if post_id(target) else None

    async def close(self) -> None:
        chrome, pw = self._chrome, self._pw
        self._ctx = self._chrome = self._pw = None
        with contextlib.suppress(Exception):
            if chrome is not None:
                await chrome.close()
        with contextlib.suppress(Exception):
            if pw is not None:
                await pw.stop()
