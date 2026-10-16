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


def bundled_libreoffice() -> Path:
    """Where `linkit install-libreoffice` puts the minimal portable LibreOffice."""
    return get_settings().data_dir / "tools" / "libreoffice"


def soffice_path() -> str | None:
    bundled = bundled_libreoffice() / "program" / "soffice.exe"
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
