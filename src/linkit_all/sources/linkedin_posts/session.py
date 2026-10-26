"""LinkedIn session helpers: is the user signed in on the `linkedin` Chrome profile?

Only URL and page checks. The app never types credentials, never clicks, never gets past a
security check: the user signs in themselves in the app browser (CLAUDE.md §5.2, plan Phase 11).
"""

import asyncio
import contextlib
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal
from urllib.parse import quote, urlsplit

from playwright.async_api import BrowserContext, Page, async_playwright

from linkit_all.apply.browser import UserBrowser, profile_dir
from linkit_all.core.chrome import open_context
from linkit_all.core.config import Settings

SessionState = Literal["ok", "logged_out", "challenge"]

FEED_URL = "https://www.linkedin.com/feed/"
LOGGED_OUT_PATHS = ("/login", "/authwall", "/uas/login", "/signup", "/uas/request-password-reset")
CHALLENGE_SELECTORS = (
    "iframe[src*='captcha' i], iframe[src*='challenge' i], iframe[title*='captcha' i], "
    "#captcha-internal, [data-captcha], form[action*='checkpoint' i]"
)
CHALLENGE_WORDS = ("let's do a quick security check", "verify you are not a robot")
SIGNED_IN_SELECTORS = "nav.global-nav, #global-nav, header#global-nav, [data-test-global-nav]"
WINDOWS = {"day": "past-24h", "week": "past-week", "month": "past-month"}


class SessionError(RuntimeError):
    """The LinkedIn profile cannot be used right now (e.g. the app browser holds it)."""


def search_url(keywords: str, window: str = "week") -> str:
    """LinkedIn content-search URL: posts matching `keywords`, newest first."""
    if window not in WINDOWS:
        raise ValueError(f"window must be one of {sorted(WINDOWS)}")
    quoted = quote(f'"{WINDOWS[window]}"', safe="")
    return (
        "https://www.linkedin.com/search/results/content/"
        f"?keywords={quote(keywords.strip(), safe='')}"
        f"&datePosted={quoted}&sortBy={quote(chr(34) + 'date_posted' + chr(34), safe='')}"
    )


def classify_url(url: str) -> SessionState | None:
    """The state a URL alone proves, else None."""
    path = urlsplit(url).path.lower().rstrip("/")
    if path.startswith("/checkpoint") or "/checkpoint/" in path:
        return "challenge"
    if any(path == p or path.startswith(p + "/") for p in LOGGED_OUT_PATHS):
        return "logged_out"
    return None


async def session_state(page: Page) -> SessionState:
    """Go to the feed and classify what LinkedIn shows. Navigation only: no typing, no clicks."""
    with contextlib.suppress(Exception):  # redirect chains and slow pages: judge what we have
        await page.goto(FEED_URL, wait_until="domcontentloaded", timeout=30000)
    by_url = classify_url(page.url)
    if by_url is not None:
        return by_url
    text = ""
    with contextlib.suppress(Exception):
        if await page.locator(CHALLENGE_SELECTORS).count():
            return "challenge"
        text = (await page.inner_text("body", timeout=5000)).lower()
    if any(w in text for w in CHALLENGE_WORDS):
        return "challenge"
    with contextlib.suppress(Exception):
        if await page.locator(SIGNED_IN_SELECTORS).count():
            return "ok"
    return "ok" if urlsplit(page.url).path.startswith("/feed") else "logged_out"


@asynccontextmanager
async def linkedin_context(
    settings: Settings, headless: bool, browser: UserBrowser | None = None
) -> AsyncIterator[BrowserContext]:
    """The persistent `linkedin` profile in installed Chrome (real Chrome, no automation flags,
    Playwright attached over CDP); Chrome and the driver are closed on exit. It never solves
    challenges or logs in."""
    if browser is not None and browser.is_open:
        raise SessionError("The app browser is open: close its window first")
    profile = profile_dir(settings, "linkedin")
    async with async_playwright() as pw:
        chrome, ctx = await open_context(pw, profile, headless=headless)
        try:
            yield ctx
        finally:
            await chrome.close()


async def check_session(
    settings: Settings, headless: bool, browser: UserBrowser | None = None
) -> SessionState:
    async with linkedin_context(settings, headless, browser) as ctx:
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        return await session_state(page)


async def capture_search(
    settings: Settings, keywords: str, out: Path, headed: bool = False
) -> SessionState:
    """Save the first screens of a content search as HTML. The file is only written when the
    session is "ok"; otherwise the state is returned."""
    async with linkedin_context(settings, headless=not headed) as ctx:
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        state = await session_state(page)
        if state != "ok":
            return state
        await page.goto(search_url(keywords), wait_until="domcontentloaded", timeout=30000)
        with contextlib.suppress(Exception):
            await page.wait_for_selector("main", timeout=15000)
        for _ in range(3):
            await page.mouse.wheel(0, 3000)
            await asyncio.sleep(random.uniform(2.0, 4.0))  # noqa: S311 - pacing, not security
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(await page.content(), encoding="utf-8")
        return "ok"


def default_capture_path(settings: Settings) -> Path:
    return settings.data_dir / "captures" / f"linkedin-{datetime.now():%Y%m%d-%H%M%S}.html"
