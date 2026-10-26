"""Launch the user's installed Chrome as a normal process and let Playwright attach over CDP.

Launch approach adapted from stealth-browser-mcp (MIT). Chrome is started without any
automation flag (no --enable-automation, no --remote-debugging-pipe, no
--disable-blink-features=AutomationControlled) and on a real, non-zero debugging port, so the
page sees an ordinary browser. Nothing here solves challenges, logs in, spoofs a fingerprint or
changes the network identity (CLAUDE.md §5.2).

One profile directory can be held by one Chrome at a time: a second launch on the same profile
exits at once (Chrome hands over to the running one) and is reported as an error.
"""

import asyncio
import contextlib
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import BrowserContext, Playwright

from linkit_all.core.tools import chrome_path, find_tool

READY_TIMEOUT_S = 20.0
CLOSE_TIMEOUT_S = 8.0
HEADLESS_WINDOW = "1280,900"

_ua_cache: dict[str, str] = {}  # real user agent per Chrome binary path


class ChromeError(RuntimeError):
    """Chrome is not installed, did not start, or did not open its debugging port."""


@dataclass
class RunningChrome:
    """A Chrome we started. `close()` ends it and its child processes; safe to call twice."""

    process: asyncio.subprocess.Process
    port: int
    profile_dir: Path
    cdp_url: str

    async def close(self) -> None:
        await _terminate(self.process)


def browser_path() -> str | None:
    """Installed Chrome, else Edge or Chromium (all speak the same CDP)."""
    if found := chrome_path():
        return found
    fallbacks = [
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        if base := os.environ.get(key):
            fallbacks.append(Path(base) / "Microsoft/Edge/Application/msedge.exe")
    return find_tool(
        ["microsoft-edge", "microsoft-edge-stable", "msedge", "chromium", "chromium-browser"],
        fallbacks,
    )


def free_port() -> int:
    """A free TCP port on loopback. Never 0: Chrome treats port 0 as automation."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def real_user_agent(headless_ua: str) -> str:
    """Headless Chrome announces itself as HeadlessChrome; send the headed string instead."""
    return headless_ua.replace("HeadlessChrome/", "Chrome/")


def _needs_no_sandbox() -> bool:
    geteuid = getattr(os, "geteuid", None)
    return geteuid is not None and geteuid() == 0  # root or a container: the sandbox cannot start


def chrome_args(
    profile_dir: Path, port: int, *, headless: bool, user_agent: str | None = None
) -> list[str]:
    args = [
        f"--user-data-dir={profile_dir}",
        f"--remote-debugging-port={port}",
        "--remote-debugging-host=127.0.0.1",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-search-engine-choice-screen",
        "--password-store=basic",
    ]
    if headless:
        args += ["--headless=new", f"--window-size={HEADLESS_WINDOW}"]
        if user_agent:
            args.append(f"--user-agent={user_agent}")
    if _needs_no_sandbox():
        args.append("--no-sandbox")
    return [*args, "about:blank"]


async def _version(port: int) -> dict[str, Any] | None:
    try:
        # trust_env=False: a system proxy must never see loopback traffic
        async with httpx.AsyncClient(trust_env=False, timeout=2.0) as client:
            r = await client.get(f"http://127.0.0.1:{port}/json/version")
        data = r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None
    return data if isinstance(data, dict) else None


async def _spawn(exe: str, args: list[str]) -> asyncio.subprocess.Process:
    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True  # own process group: close() can end the children too
    return await asyncio.create_subprocess_exec(
        exe,
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        **kwargs,
    )


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """End Chrome and its children: polite first (so the profile is saved), then forced."""
    if proc.returncode is not None and sys.platform == "win32":
        return  # nothing left to signal; there is no process group to sweep
    for force in (False, True):
        _signal_tree(proc, force)
        with contextlib.suppress(TimeoutError, ProcessLookupError):
            await asyncio.wait_for(proc.wait(), CLOSE_TIMEOUT_S if not force else 5.0)
            break
    if sys.platform != "win32":  # the leader may be gone while renderers linger in the group
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGKILL)


def _signal_tree(proc: asyncio.subprocess.Process, force: bool) -> None:
    if sys.platform == "win32":
        cmd = ["taskkill", "/PID", str(proc.pid), "/T"] + (["/F"] if force else [])
        with contextlib.suppress(OSError):
            subprocess.run(cmd, capture_output=True, check=False, timeout=10)  # noqa: S603
        return
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL if force else signal.SIGTERM)


async def _wait_ready(
    proc: asyncio.subprocess.Process, port: int, timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        if proc.returncode is not None:
            raise ChromeError(
                "Chrome exited at start: is this profile open in another Chrome window?"
            )
        if (info := await _version(port)) is not None:
            return info
        if time.monotonic() >= deadline:
            raise ChromeError(f"Chrome did not open its debugging port within {timeout:.0f} s")
        await asyncio.sleep(0.2)


async def _start(
    exe: str, profile_dir: Path, *, headless: bool, user_agent: str | None, timeout: float
) -> tuple[asyncio.subprocess.Process, int, dict[str, Any]]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = free_port()
    proc = await _spawn(
        exe, chrome_args(profile_dir, port, headless=headless, user_agent=user_agent)
    )
    try:
        return proc, port, await _wait_ready(proc, port, timeout)
    except BaseException:
        await _terminate(proc)
        raise


async def _headless_ua(exe: str, timeout: float) -> str:
    """The user agent a headed Chrome would send, read once per binary from a short headless run."""
    if exe not in _ua_cache:
        with tempfile.TemporaryDirectory(prefix="linkit-ua-") as tmp:
            proc, _, info = await _start(
                exe, Path(tmp) / "p", headless=True, user_agent=None, timeout=timeout
            )
            try:
                _ua_cache[exe] = real_user_agent(str(info.get("User-Agent", "")))
            finally:
                await _terminate(proc)
    return _ua_cache[exe]


async def launch_chrome(
    profile_dir: Path, *, headless: bool, timeout: float = READY_TIMEOUT_S
) -> RunningChrome:
    exe = browser_path()
    if exe is None:
        raise ChromeError("Google Chrome is not installed: https://www.google.com/chrome/")
    ua = await _headless_ua(exe, timeout) if headless else None
    proc, port, _ = await _start(
        exe, profile_dir, headless=headless, user_agent=ua, timeout=timeout
    )
    return RunningChrome(proc, port, profile_dir, f"http://127.0.0.1:{port}")


async def connect(pw: Playwright, running: RunningChrome) -> BrowserContext:
    """Attach Playwright to the running Chrome and return its profile (default) context."""
    browser = await pw.chromium.connect_over_cdp(running.cdp_url)
    return browser.contexts[0]


async def open_context(
    pw: Playwright, profile_dir: Path, *, headless: bool
) -> tuple[RunningChrome, BrowserContext]:
    """launch_chrome + connect; Chrome is ended again if attaching fails."""
    running = await launch_chrome(profile_dir, headless=headless)
    try:
        return running, await connect(pw, running)
    except BaseException:
        await running.close()
        raise
