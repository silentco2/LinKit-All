"""Optional LibreOffice install into LinKit's own data folder (CLAUDE.md §6).

The trimmed bundle is downloaded from `lo_bundle_url`, checked against the pinned SHA-256
*before* anything is unpacked, and only then installed. Nothing downloaded is ever run."""

import asyncio
import hashlib
import platform
import shutil
import sys
import zipfile
from pathlib import Path

import httpx
from loguru import logger

from linkit_all.core.config import LO_BUNDLE_SHA256, LO_BUNDLE_URL, Settings
from linkit_all.core.tools import bundled_libreoffice, soffice_path

CHUNK = 1 << 16


def install_libreoffice(source: Path, data_dir: Path | None = None) -> Path:
    """Unpack a bundle (zip or folder) into the data dir. ValueError when it is not a bundle."""
    dest = bundled_libreoffice(data_dir)
    shutil.rmtree(dest, ignore_errors=True)
    try:
        if source.is_dir():
            shutil.copytree(source, dest)
        else:
            with zipfile.ZipFile(source) as z:
                z.extractall(dest)  # zipfile strips absolute paths and ".." parts
    except (OSError, zipfile.BadZipFile) as e:
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError(f"{source} is not a LibreOffice bundle ({type(e).__name__})") from e
    if not (dest / "program" / "soffice.exe").is_file():
        shutil.rmtree(dest, ignore_errors=True)
        raise ValueError(f"{source} does not contain program/soffice.exe")
    return dest


class LibreOfficeInstaller:
    """One background download at a time; `status()` is what the UI polls."""

    def __init__(
        self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.settings, self._transport = settings, transport
        self.installing = False
        self.progress = 0.0
        self.error: str | None = None
        self._task: asyncio.Task[None] | None = None  # kept so it is not collected mid-flight

    def available(self) -> bool:
        s = self.settings
        if not (s.lo_bundle_url.startswith("https://") and s.lo_bundle_sha256.strip()):
            return False
        own = (s.lo_bundle_url, s.lo_bundle_sha256) != (LO_BUNDLE_URL, LO_BUNDLE_SHA256)
        # The hosted bundle is Windows x64 only; a bundle the user pointed us at is theirs to judge.
        x64 = platform.machine().lower() in ("amd64", "x86_64")
        return own or (sys.platform == "win32" and x64)

    def status(self) -> dict[str, object]:
        installing, progress, error = self.installing, self.progress, self.error
        path = soffice_path(self.settings.data_dir)  # after the flag: never "done" but "missing"
        return {
            "installed": path is not None,
            "path": path,
            "installing": installing,
            "progress": round(progress, 3),
            "error": error,
            "available": self.available(),
        }

    def start(self) -> bool:
        """Begin the download. False when one is already running; needs an event loop."""
        if self.installing:
            return False
        self.installing, self.progress, self.error = True, 0.0, None
        self._task = asyncio.create_task(self._run())
        return True

    async def _run(self) -> None:
        part = self.settings.data_dir / "tools" / "download" / "libreoffice.zip.part"
        try:
            part.parent.mkdir(parents=True, exist_ok=True)
            digest = await self._download(part)
            if digest != self.settings.lo_bundle_sha256.strip().lower():
                raise ValueError(
                    "The download does not match the expected checksum, so it was not installed."
                )
            await asyncio.to_thread(install_libreoffice, part, self.settings.data_dir)
            self.progress = 1.0
        except Exception as e:  # shown in the UI; the app keeps working without LibreOffice
            logger.warning("LibreOffice install failed: {}", type(e).__name__)
            self.error = (
                str(e) if isinstance(e, ValueError) else f"Download failed ({type(e).__name__})."
            )
        finally:
            part.unlink(missing_ok=True)
            self.installing = False

    async def _download(self, part: Path) -> str:
        """Stream the zip to `part` and return its SHA-256 hex digest."""
        sha, done = hashlib.sha256(), 0
        client = httpx.AsyncClient(transport=self._transport, follow_redirects=True, timeout=60)
        async with client, client.stream("GET", self.settings.lo_bundle_url) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length") or 0)
            with part.open("wb") as f:
                async for chunk in resp.aiter_bytes(CHUNK):
                    f.write(chunk)
                    sha.update(chunk)
                    done += len(chunk)
                    if total:
                        self.progress = min(done / total, 0.99)  # 1.0 only once installed
        return sha.hexdigest()
