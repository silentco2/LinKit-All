"""Locate external programs (PATH first, then default install dirs on Windows/macOS)."""

import os
import shutil
from pathlib import Path

from linkit_all.core.config import get_settings


def is_snap(path: str) -> bool:
    """A Snap build (or Ubuntu's wrapper script that starts one). Snap confinement cannot open
    the app's hidden data folder, so such a program is never used."""
    for p in (path, os.path.realpath(path)):
        if p.replace("\\", "/").startswith(("/snap/", "/var/lib/snapd/snap/")):
            return True
    if os.path.basename(path) in ("chromium", "chromium-browser"):
        try:
            with open(path, "rb") as f:
                head = f.read(512)
        except OSError:
            return False
        return head.startswith(b"#!") and b"snap" in head
    return False


def find_tool(names: list[str], fallbacks: list[Path]) -> str | None:
    for name in names:
        if (found := shutil.which(name)) and not is_snap(found):
            return found
    return next((str(p) for p in fallbacks if p.is_file()), None)


def _program_dirs() -> list[Path]:
    keys = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
    return [Path(v) for k in keys if (v := os.environ.get(k))]


def _mac_apps(app: str, exe: str) -> list[Path]:
    """A macOS app's binary in /Applications and in the user's own ~/Applications."""
    bases = (Path("/Applications"), Path.home() / "Applications")
    return [base / f"{app}.app/Contents/MacOS/{exe}" for base in bases]


def bundled_libreoffice(data_dir: Path | None = None) -> Path:
    """Where `linkit install-libreoffice` (or the in-app install) puts the minimal portable
    LibreOffice."""
    return (data_dir or get_settings().data_dir) / "tools" / "libreoffice"


SOFFICE_NAMES = ["soffice", "libreoffice"]
CHROME_NAMES = ["google-chrome", "google-chrome-stable", "chrome"]
OTHER_BROWSERS = [
    "microsoft-edge", "microsoft-edge-stable", "msedge", "brave-browser", "brave", "chromium",
    "chromium-browser",
]  # fmt: skip
BROWSER_NAMES = CHROME_NAMES + OTHER_BROWSERS


def snap_only(names: list[str]) -> bool:
    """True when one of `names` is on PATH only as a Snap build (for `linkit doctor`)."""
    return any((w := shutil.which(n)) and is_snap(w) for n in names)


def soffice_path(data_dir: Path | None = None) -> str | None:
    bundled = bundled_libreoffice(data_dir) / "program" / "soffice.exe"
    if bundled.is_file():
        return str(bundled)
    fallbacks = [d / "LibreOffice/program/soffice.exe" for d in _program_dirs()]
    fallbacks += _mac_apps("LibreOffice", "soffice")
    return find_tool(SOFFICE_NAMES, fallbacks)


def tectonic_path() -> str | None:
    cargo = Path.home() / ".cargo" / "bin"
    return find_tool(["tectonic"], [cargo / "tectonic.exe", cargo / "tectonic"])


def chrome_path() -> str | None:
    fallbacks = [d / "Google/Chrome/Application/chrome.exe" for d in _program_dirs()]
    fallbacks += _mac_apps("Google Chrome", "Google Chrome")
    return find_tool(CHROME_NAMES, fallbacks)


CHROMIUM_URL = "https://www.chromium.org/getting-involved/download-chromium/"
CHROMIUM_HINT = f"install Chromium ({CHROMIUM_URL}); not needed if you have Chrome, Edge or Brave"


def browser_path() -> str | None:
    """The browser for finding and applying: Chrome, else Edge, Brave or Chromium (all speak
    the same CDP). Edge ships with Windows, so most users need nothing extra."""
    if found := chrome_path():
        return found
    fallbacks = [
        *_mac_apps("Microsoft Edge", "Microsoft Edge"),
        *_mac_apps("Brave Browser", "Brave Browser"),
        *_mac_apps("Chromium", "Chromium"),
    ]
    for base in _program_dirs():  # Brave's per-user install lives under LOCALAPPDATA
        fallbacks.append(base / "Microsoft/Edge/Application/msedge.exe")
        fallbacks.append(base / "BraveSoftware/Brave-Browser/Application/brave.exe")
    return find_tool(OTHER_BROWSERS, fallbacks)
