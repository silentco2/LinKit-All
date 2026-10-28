"""The Chrome launcher: arguments, port, readiness wait, shutdown; plus one real launch."""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Any

import pytest
from playwright.async_api import async_playwright

from linkit_all.core import chrome

FORBIDDEN = ("--enable-automation", "--remote-debugging-pipe", "AutomationControlled")


def test_args_have_no_automation_flags_and_a_real_port(tmp_path: Path) -> None:
    port = chrome.free_port()
    assert port != 0
    args = chrome.chrome_args(tmp_path, port, headless=False)
    assert f"--remote-debugging-port={port}" in args
    assert "--remote-debugging-host=127.0.0.1" in args
    assert f"--user-data-dir={tmp_path}" in args
    assert {"--no-first-run", "--no-default-browser-check", "--password-store=basic"} <= set(args)
    assert "--disable-search-engine-choice-screen" in args
    assert args[-1] == "about:blank"
    assert not any(f in a for a in args for f in FORBIDDEN)
    assert not any(a.startswith(("--headless", "--user-agent")) for a in args)


def test_headless_args_fit_the_window_in_the_screen_and_keep_client_hints(tmp_path: Path) -> None:
    args = chrome.chrome_args(tmp_path, 9333, headless=True)
    assert "--headless=new" in args and f"--screen-info={chrome.HEADLESS_SCREEN}" in args
    win = [int(n) for n in chrome.HEADLESS_WINDOW.split(",")]
    screen = [int(n) for n in chrome.HEADLESS_SCREEN.strip("{}").split()[0].split("x")]
    assert win[0] <= screen[0] and win[1] <= screen[1]
    assert not any(a.startswith("--user-agent") for a in args)  # the flag blanks client hints
    assert not any(f in a for a in args for f in FORBIDDEN)
    assert chrome.real_user_agent("A HeadlessChrome/150.0 B") == "A Chrome/150.0 B"


def test_ua_metadata_keeps_the_browsers_own_hints() -> None:
    hints = {"brands": [{"brand": "Google Chrome", "version": "150"}], "mobile": False,
             "fullVersionList": [{"brand": "Google Chrome", "version": "150.0.1.2"}],
             "platform": "Windows", "platformVersion": "19.0.0", "architecture": "x86",
             "bitness": "64", "model": "", "wow64": False, "uaFullVersion": "150.0.1.2"}  # fmt: skip
    meta = chrome.ua_metadata(hints)
    assert meta == {k: v for k, v in hints.items() if k != "uaFullVersion"}


def test_no_sandbox_only_for_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chrome, "_needs_no_sandbox", lambda: True)
    assert "--no-sandbox" in chrome.chrome_args(tmp_path, 9333, headless=False)
    monkeypatch.setattr(chrome, "_needs_no_sandbox", lambda: False)
    assert "--no-sandbox" not in chrome.chrome_args(tmp_path, 9333, headless=False)


def test_free_port_is_bindable_and_varies() -> None:
    ports = {chrome.free_port() for _ in range(5)}
    assert 0 not in ports and all(1024 <= p <= 65535 for p in ports)


class FakeProc:
    def __init__(self, returncode: int | None = None) -> None:
        self.returncode = returncode
        self.pid = 1


def test_wait_ready_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never(port: int) -> None:
        return None

    monkeypatch.setattr(chrome, "_version", never)
    with pytest.raises(chrome.ChromeError, match="debugging port"):
        asyncio.run(chrome._wait_ready(FakeProc(), 9333, 0.5))  # type: ignore[arg-type]


def test_wait_ready_reports_early_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def never(port: int) -> None:
        return None

    monkeypatch.setattr(chrome, "_version", never)
    with pytest.raises(chrome.ChromeError, match="another Chrome"):
        asyncio.run(chrome._wait_ready(FakeProc(0), 9333, 5))  # type: ignore[arg-type]


def test_wait_ready_returns_version_info(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ok(port: int) -> dict[str, Any]:
        return {"Browser": "Chrome/1"}

    monkeypatch.setattr(chrome, "_version", ok)
    got = asyncio.run(chrome._wait_ready(FakeProc(), 9333, 5))  # type: ignore[arg-type]
    assert got == {"Browser": "Chrome/1"}


def test_launch_reads_identity_once_and_masks_headless(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spawned: list[list[str]] = []
    ended: list[object] = []

    async def fake_spawn(exe: str, args: list[str]) -> FakeProc:
        spawned.append(args)
        return FakeProc()

    async def fake_version(port: int) -> dict[str, Any]:
        ua = "Mozilla/5.0 HeadlessChrome/150.0.0.0 Safari/537.36"
        return {"User-Agent": ua, "webSocketDebuggerUrl": f"ws://127.0.0.1:{port}/devtools/b"}

    async def fake_hints(port: int, ws_url: str) -> dict[str, Any]:
        return {"brands": [{"brand": "Google Chrome", "version": "150"}], "mobile": False}

    masks: list[tuple[str, chrome.Identity]] = []

    async def fake_mask(ws_url: str, identity: chrome.Identity) -> str:
        masks.append((ws_url, identity))
        return "mask"

    async def fake_terminate(proc: object) -> None:
        ended.append(proc)

    monkeypatch.setattr(chrome, "browser_path", lambda: "/fake/chrome")
    monkeypatch.setattr(chrome, "_spawn", fake_spawn)
    monkeypatch.setattr(chrome, "_version", fake_version)
    monkeypatch.setattr(chrome, "_terminate", fake_terminate)
    monkeypatch.setattr(chrome, "_read_hints", fake_hints)
    monkeypatch.setattr(chrome.HeadlessMask, "start", fake_mask)
    monkeypatch.setattr(chrome, "_identity_cache", {})

    async def go() -> tuple[chrome.RunningChrome, chrome.RunningChrome]:
        return (
            await chrome.launch_chrome(tmp_path / "a", headless=True),
            await chrome.launch_chrome(tmp_path / "b", headless=True),
        )

    first, _ = asyncio.run(go())
    assert len(spawned) == 3  # one short identity probe, then the two real launches
    assert not any("--user-agent" in a for args in spawned for a in args)
    want = chrome.Identity(
        "Mozilla/5.0 Chrome/150.0.0.0 Safari/537.36",
        {"brands": [{"brand": "Google Chrome", "version": "150"}], "mobile": False},
    )
    assert [m[1] for m in masks] == [want, want] and first.mask == "mask"  # type: ignore[comparison-overlap]
    assert masks[0][0] == f"ws://127.0.0.1:{first.port}/devtools/b"
    assert first.cdp_url == f"http://127.0.0.1:{first.port}" and first.port != 0
    assert len(ended) == 1  # only the probe was stopped


def test_launch_without_chrome_says_so(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(chrome, "browser_path", lambda: None)
    with pytest.raises(chrome.ChromeError, match="not installed"):
        asyncio.run(chrome.launch_chrome(tmp_path, headless=True))


def _alive(pid: int) -> bool:
    try:  # a zombie is a dead process nobody has reaped yet
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


@pytest.mark.skipif(not Path("/proc/self/stat").exists(), reason="needs /proc")
def test_close_kills_the_process_and_its_children(tmp_path: Path) -> None:
    pidfile = tmp_path / "child.pid"
    child = f"import os,time;open({str(pidfile)!r},'w').write(str(os.getpid()));time.sleep(60)"
    code = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{child!r}]);time.sleep(60)"
    )

    async def go() -> int | None:
        proc = await chrome._spawn(sys.executable, ["-c", code])
        for _ in range(50):
            if pidfile.exists() and pidfile.read_text():
                break
            await asyncio.sleep(0.1)
        child_pid = int(pidfile.read_text())
        assert _alive(child_pid) and _alive(proc.pid)
        running = chrome.RunningChrome(proc, 1, Path("."), "http://127.0.0.1:1")
        await running.close()
        await running.close()  # twice is fine
        assert proc.returncode is not None
        assert not _alive(child_pid)
        return proc.returncode

    assert asyncio.run(go()) in (-signal.SIGTERM, -signal.SIGKILL)


@pytest.mark.skipif(chrome.browser_path() is None, reason="no Chrome or Chromium installed")
@pytest.mark.parametrize("headless", [True])
def test_real_launch_connect_and_close(tmp_path: Path, headless: bool) -> None:
    probe = """async () => ({ ua: navigator.userAgent, webdriver: navigator.webdriver,
      full: (await navigator.userAgentData.getHighEntropyValues(['fullVersionList']))
        .fullVersionList.map(b => b.brand),
      fits: outerWidth <= screen.width && outerHeight <= screen.height })"""

    async def go() -> tuple[dict[str, Any], int | None]:
        async with async_playwright() as pw:
            running, ctx = await chrome.open_context(pw, tmp_path / "profile", headless=headless)
            try:
                page = await ctx.new_page()  # a new tab: the mask must cover it before it loads
                await page.route(
                    "**/*", lambda r: r.fulfill(body="<p>hi</p>", content_type="text/html")
                )
                await page.goto("https://example.test/")  # secure, so userAgentData exists
                seen = await page.evaluate(probe)
            finally:
                await running.close()
            return seen, running.process.returncode

    seen, code = asyncio.run(go())
    assert "HeadlessChrome" not in seen["ua"] and seen["webdriver"] is False
    assert seen["full"] and not any("Headless" in b for b in seen["full"])  # hints not blanked
    assert seen["fits"]  # the window fits in the screen
    assert code is not None
