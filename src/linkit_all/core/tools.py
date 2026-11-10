"""Locate external programs (PATH first, then default install dirs on Windows/macOS)."""

import os
import shutil
from pathlib import Path

from linkit_all.core.config import get_settings


def find_tool(names: list[str], fallbacks: list[Path]) -> str | None:
    for name in names:
        if found := shutil.which(name):
            return found
    return next((str(p) for p in fallbacks if p.is_file()), None)


def _program_dirs() -> list[Path]:
    keys = ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA")
    return [Path(v) for k in keys if (v := os.environ.get(k))]


def bundled_libreoffice(data_dir: Path | None = None) -> Path:
    """Where `linkit install-libreoffice` (or the in-app install) puts the minimal portable
    LibreOffice."""
    return (data_dir or get_settings().data_dir) / "tools" / "libreoffice"


def soffice_path(data_dir: Path | None = None) -> str | None:
    bundled = bundled_libreoffice(data_dir) / "program" / "soffice.exe"
    if bundled.is_file():
        return str(bundled)
    fallbacks = [d / "LibreOffice/program/soffice.exe" for d in _program_dirs()]
    fallbacks.append(Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"))
    return find_tool(["soffice", "libreoffice"], fallbacks)


def tectonic_path() -> str | None:
    cargo = Path.home() / ".cargo" / "bin"
    return find_tool(["tectonic"], [cargo / "tectonic.exe", cargo / "tectonic"])


def chrome_path() -> str | None:
    fallbacks = [d / "Google/Chrome/Application/chrome.exe" for d in _program_dirs()]
    fallbacks.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    return find_tool(["google-chrome", "google-chrome-stable", "chrome"], fallbacks)


CHROMIUM_URL = "https://www.chromium.org/getting-involved/download-chromium/"
CHROMIUM_HINT = f"install Chromium ({CHROMIUM_URL}); not needed if you have Chrome, Edge or Brave"


def browser_path() -> str | None:
    """The browser for finding and applying: Chrome, else Edge, Brave or Chromium (all speak
    the same CDP). Edge ships with Windows, so most users need nothing extra."""
    if found := chrome_path():
        return found
    fallbacks = [
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    for base in _program_dirs():  # Brave's per-user install lives under LOCALAPPDATA
        fallbacks.append(base / "Microsoft/Edge/Application/msedge.exe")
        fallbacks.append(base / "BraveSoftware/Brave-Browser/Application/brave.exe")
    return find_tool(
        ["microsoft-edge", "microsoft-edge-stable", "msedge", "brave-browser", "brave",
         "chromium", "chromium-browser"],
        fallbacks,
    )  # fmt: skip
