"""Launch the user's installed Chrome as a normal process and let Playwright attach over CDP.

Launch approach adapted from stealth-browser-mcp (MIT). Chrome is started without any
automation flag (no --enable-automation, no --remote-debugging-pipe, no
--disable-blink-features=AutomationControlled) and on a real, non-zero debugging port, so the
page sees an ordinary browser. Nothing here solves challenges, logs in or changes the network
identity (CLAUDE.md §5.2).

Headless only (maintainer 2026-10-29): the virtual screen is set so the window fits inside it,
and every tab and worker gets the real Chrome user agent (no "HeadlessChrome") together with the
browser's own client hints (full version list, platform version...), set over CDP before the
target runs. A `--user-agent` flag would blank those hints, which is itself a tell.

One profile directory can be held by one Chrome at a time: a second launch on the same profile
exits at once (Chrome hands over to the running one) and is reported as an error.
"""

import asyncio
import contextlib
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from playwright.async_api import BrowserContext, Playwright
from websockets.asyncio.client import ClientConnection
from websockets.asyncio.client import connect as ws_connect

from linkit_all.core.tools import chrome_path, find_tool

READY_TIMEOUT_S = 20.0
CLOSE_TIMEOUT_S = 8.0
HEADLESS_WINDOW = "1280,900"
# headless virtual display: the window must fit inside it (the default 800x600 does not)
# ponytail: fixed 1080p like the maintainer's screen; read the OS screen size if users differ
HEADLESS_SCREEN = "{1920x1080}"
UA_CH = (
    "navigator.userAgentData.getHighEntropyValues(['architecture', 'bitness', 'formFactors', "
    "'fullVersionList', 'model', 'platformVersion', 'wow64'])"
)
AUTO_ATTACH = {"autoAttach": True, "waitForDebuggerOnStart": True, "flatten": True}


@dataclass(frozen=True)
class Identity:
    """What a headed Chrome of this binary says about itself: user agent + client hints."""

    user_agent: str
    metadata: dict[str, Any]  # CDP Emulation.UserAgentMetadata


_identity_cache: dict[str, Identity] = {}  # per Chrome binary path


class ChromeError(RuntimeError):
    """Chrome is not installed, did not start, or did not open its debugging port."""


class Cdp:
    """A minimal CDP client on one websocket, flat sessions (`session` = sessionId)."""

    def __init__(self, ws: ClientConnection) -> None:
        self._ws = ws
        self._ids = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self.on_event: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._reader = asyncio.create_task(self._read())

    @classmethod
    async def open(cls, ws_url: str) -> "Cdp":
        return cls(await ws_connect(ws_url, max_size=None, proxy=None))

    async def send(
        self, method: str, params: dict[str, Any] | None = None, session: str | None = None
    ) -> dict[str, Any]:
        self._ids += 1
        msg: dict[str, Any] = {"id": self._ids, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        fut = self._pending[self._ids] = asyncio.get_running_loop().create_future()
        await self._ws.send(json.dumps(msg))
        reply = await fut
        if "error" in reply:
            raise ChromeError(f"{method}: {reply['error'].get('message')}")
        return dict(reply.get("result", {}))

    async def _read(self) -> None:
        with contextlib.suppress(Exception):  # socket closed: Chrome ended or close() was called
            async for raw in self._ws:
                msg = json.loads(raw)
                if (fut := self._pending.pop(msg.get("id", -1), None)) is not None:
                    fut.set_result(msg)
                elif (cb := self.on_event.get(msg.get("method", ""))) is not None:
                    cb(msg.get("params", {}))
        for fut in self._pending.values():
            if not fut.done():
                fut.set_result({"error": {"message": "connection closed"}})

    async def close(self) -> None:
        await self._ws.close()
        with contextlib.suppress(BaseException):
            await self._reader


class HeadlessMask:
    """Holds every new tab, frame and worker (auto-attach, paused) until it carries the real
    user agent and client hints, then lets it run. Lives as long as the Chrome it watches."""

    def __init__(self, cdp: Cdp, identity: Identity) -> None:
        self.cdp = cdp
        self.override = {"userAgent": identity.user_agent, "userAgentMetadata": identity.metadata}
        self.tasks: set[asyncio.Task[None]] = set()
        cdp.on_event["Target.attachedToTarget"] = self._on_attached

    @classmethod
    async def start(cls, ws_url: str, identity: Identity) -> "HeadlessMask":
        mask = cls(await Cdp.open(ws_url), identity)
        await mask.cdp.send("Target.setAutoAttach", AUTO_ATTACH)  # existing targets attach too
        await asyncio.gather(*mask.tasks)  # the start page is covered before anyone navigates
        return mask

    def _on_attached(self, params: dict[str, Any]) -> None:
        task = asyncio.create_task(self._cover(params))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def _cover(self, params: dict[str, Any]) -> None:
        sid, kind = params["sessionId"], params["targetInfo"]["type"]
        try:
            with contextlib.suppress(ChromeError):  # the target may already be gone
                if kind in ("page", "iframe"):
                    await self.cdp.send("Emulation.setUserAgentOverride", self.override, sid)
                    await self.cdp.send("Target.setAutoAttach", AUTO_ATTACH, sid)  # its workers
                elif kind in ("worker", "shared_worker", "service_worker"):
                    await self.cdp.send("Network.setUserAgentOverride", self.override, sid)
        finally:
            if params.get("waitingForDebugger"):  # never leave a target paused
                with contextlib.suppress(ChromeError):
                    await self.cdp.send("Runtime.runIfWaitingForDebugger", None, sid)

    async def close(self) -> None:
        await self.cdp.close()


@dataclass
class RunningChrome:
    """A Chrome we started. `close()` ends it and its child processes; safe to call twice."""

    process: asyncio.subprocess.Process
    port: int
    profile_dir: Path
    cdp_url: str
    mask: HeadlessMask | None = None

    async def close(self) -> None:
        if self.mask is not None:
            mask, self.mask = self.mask, None
            with contextlib.suppress(Exception):
                await mask.close()
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


def chrome_args(profile_dir: Path, port: int, *, headless: bool) -> list[str]:
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
        args += [
            "--headless=new",
            f"--window-size={HEADLESS_WINDOW}",
            f"--screen-info={HEADLESS_SCREEN}",
        ]
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
    exe: str, profile_dir: Path, *, headless: bool, timeout: float
) -> tuple[asyncio.subprocess.Process, int, dict[str, Any]]:
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = free_port()
    proc = await _spawn(exe, chrome_args(profile_dir, port, headless=headless))
    try:
        return proc, port, await _wait_ready(proc, port, timeout)
    except BaseException:
        await _terminate(proc)
        raise


def ua_metadata(hints: dict[str, Any]) -> dict[str, Any]:
    """navigator.userAgentData.getHighEntropyValues() -> CDP UserAgentMetadata (same values)."""
    keys = ("brands", "fullVersionList", "platform", "platformVersion", "architecture", "model",
            "mobile", "bitness", "wow64", "formFactors")  # fmt: skip
    return {k: hints[k] for k in keys if k in hints}


async def _read_hints(port: int, ws_url: str) -> dict[str, Any]:
    """The browser's own client hints, from a page on its loopback debugging origin (a secure
    context, so navigator.userAgentData exists)."""
    cdp = await Cdp.open(ws_url)
    try:
        url = f"http://127.0.0.1:{port}/json/version"
        target = await cdp.send("Target.createTarget", {"url": url})
        sid = (await cdp.send("Target.attachToTarget", {**target, "flatten": True}))["sessionId"]
        ready = {"expression": "isSecureContext && !!navigator.userAgentData"}
        for _ in range(50):
            if (await cdp.send("Runtime.evaluate", ready, sid)).get("result", {}).get("value"):
                break
            await asyncio.sleep(0.1)
        ask = {"expression": UA_CH, "awaitPromise": True, "returnByValue": True}
        hints = (await cdp.send("Runtime.evaluate", ask, sid)).get("result", {}).get("value")
        if not isinstance(hints, dict):
            raise ChromeError("Chrome did not report its client hints")
        return hints
    finally:
        await cdp.close()


async def _headless_identity(exe: str, timeout: float) -> Identity:
    """User agent and client hints of this binary, read once per binary from a short headless
    run (its hints already name the real browser; only the UA string says HeadlessChrome)."""
    if exe not in _identity_cache:
        with tempfile.TemporaryDirectory(prefix="linkit-ua-") as tmp:
            proc, port, info = await _start(exe, Path(tmp) / "p", headless=True, timeout=timeout)
            try:
                hints = await _read_hints(port, str(info["webSocketDebuggerUrl"]))
                ua = real_user_agent(str(info.get("User-Agent", "")))
                _identity_cache[exe] = Identity(ua, ua_metadata(hints))
            finally:
                await _terminate(proc)
    return _identity_cache[exe]


async def launch_chrome(
    profile_dir: Path, *, headless: bool, timeout: float = READY_TIMEOUT_S
) -> RunningChrome:
    exe = browser_path()
    if exe is None:
        raise ChromeError("Google Chrome is not installed: https://www.google.com/chrome/")
    identity = await _headless_identity(exe, timeout) if headless else None
    proc, port, info = await _start(exe, profile_dir, headless=headless, timeout=timeout)
    running = RunningChrome(proc, port, profile_dir, f"http://127.0.0.1:{port}")
    if identity is not None:
        try:
            running.mask = await HeadlessMask.start(str(info["webSocketDebuggerUrl"]), identity)
        except BaseException:
            await running.close()
            raise
    return running


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
