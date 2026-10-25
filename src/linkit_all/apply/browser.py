"""Two small browser helpers for the apply stage.

* UserBrowser: a headed Chrome window the USER drives (sign in, solve a CAPTCHA, enter a 2FA
  code) on the same persistent profile the apply runner used, so the session carries over to
  Retry. The app never types or clicks in it (CLAUDE.md §5.7).
* live_frames: a JPEG of the page the apply stage is working on, announced to the Live Run screen
  (via `on_frame`) each time a new one is written.
"""

import asyncio
import contextlib
import time
from collections.abc import Callable
from pathlib import Path

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from linkit_all.apply.handlers import HANDLERS
from linkit_all.core.config import Settings

LIVE_MAX_AGE_S = 30  # a frame older than this is left over from a crashed run


def profile_dir(settings: Settings, ats: str | None) -> Path:
    """One persistent Chrome profile per ATS handler, else a shared "generic" one. "linkedin" is
    its own profile (the user's LinkedIn sign-in), never shared with the others."""
    name = ats if ats in HANDLERS or ats == "linkedin" else "generic"
    return settings.data_dir / "browser" / name


def live_shot_path(settings: Settings) -> Path:
    return settings.data_dir / "live" / "current.jpg"


def fresh_live_shot(settings: Settings) -> Path | None:
    path = live_shot_path(settings)
    try:
        return path if time.time() - path.stat().st_mtime <= LIVE_MAX_AGE_S else None
    except OSError:
        return None


_live_active: dict[Path, int] = {}  # pages currently writing each frame file


async def live_frames(
    page: Page, path: Path, every: float = 3.0, on_frame: Callable[[], None] | None = None
) -> None:
    """Save a viewport JPEG every `every` seconds until cancelled. Several pages may share
    `path` (latest frame wins; ponytail: no per-page view); the file is removed when the last
    one stops. `on_frame` is called after each frame is on disk, never otherwise."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{id(page)}.tmp")  # per page: writers never share a temp file
    _live_active[path] = _live_active.get(path, 0) + 1
    try:
        while True:
            with contextlib.suppress(Exception):  # page mid-navigation, closed, or file in use
                tmp.write_bytes(await page.screenshot(type="jpeg", quality=60))
                tmp.replace(path)  # atomic: the endpoint never serves half a frame
                if on_frame is not None:
                    on_frame()
            await asyncio.sleep(every)
    finally:
        _live_active[path] -= 1
        last = _live_active[path] == 0
        if last:
            del _live_active[path]
        for f in (path, tmp) if last else (tmp,):
            with contextlib.suppress(OSError):
                f.unlink(missing_ok=True)


class UserBrowser:
    """At most one headed window for the user, closed by them or by `close()`."""

    def __init__(self) -> None:
        self._pw: Playwright | None = None
        self._ctx: BrowserContext | None = None
        self._opening = False
        self._stopping: asyncio.Task[None] | None = None  # keeps the task referenced
        self.item_id: int | None = None

    @property
    def is_open(self) -> bool:
        return self._opening or self._ctx is not None

    async def open(self, profile: Path, url: str, item_id: int) -> None:
        if self.is_open:
            raise RuntimeError("the app browser is already open")
        self._opening = True
        try:
            await self._stop_pw(self._pw)  # driver left over from a window the user closed
            profile.mkdir(parents=True, exist_ok=True)
            self._pw = await async_playwright().start()
            ctx = await self._pw.chromium.launch_persistent_context(
                str(profile), channel="chrome", headless=False, no_viewport=True
            )
            self._ctx, self.item_id = ctx, item_id
            ctx.on("close", lambda _: self._forget())  # the user closed the window
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            with contextlib.suppress(Exception):  # slow page: the window stays, the user retries
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
        except Exception:
            await self.close()
            raise
        finally:
            self._opening = False

    def _forget(self) -> None:
        self._ctx, self.item_id = None, None
        # ponytail: the Playwright driver is stopped here, else by the next open() / shutdown
        with contextlib.suppress(RuntimeError):  # no running loop
            if self._pw is not None:
                self._stopping = asyncio.get_running_loop().create_task(self._stop_pw(self._pw))
                self._pw = None

    @staticmethod
    async def _stop_pw(pw: Playwright | None) -> None:
        with contextlib.suppress(Exception):
            if pw is not None:
                await pw.stop()

    async def close(self) -> None:
        ctx, pw = self._ctx, self._pw
        self._ctx, self._pw, self.item_id = None, None, None
        with contextlib.suppress(Exception):
            if ctx is not None:
                await ctx.close()
        with contextlib.suppress(Exception):
            if pw is not None:
                await pw.stop()
