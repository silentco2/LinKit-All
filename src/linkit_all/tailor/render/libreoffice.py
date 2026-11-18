"""LibreOffice headless conversions: DOCX -> PDF (what gets submitted), ODT -> DOCX (CV input)."""

import subprocess
import threading
from pathlib import Path

from linkit_all.core.config import get_settings
from linkit_all.core.tools import soffice_path

# ponytail: one soffice at a time (instances sharing a profile collide); per-call profiles
# if rendering ever becomes the bottleneck.
_lock = threading.Lock()


def profile_dir() -> Path:
    """LibreOffice's profile: in the user's own data folder, never a shared /tmp name another
    local user could pre-create."""
    path = get_settings().data_dir / "tools" / "lo-profile"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


class RenderError(RuntimeError):
    pass


def convert(src: Path, fmt: str, out_dir: Path, timeout_s: float = 180) -> Path:
    """Convert `src` to `fmt` ("pdf", "docx") as out_dir/<stem>.<fmt>."""
    exe = soffice_path()
    if exe is None:
        raise RenderError("LibreOffice not found; install it and run `linkit doctor`")
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{src.stem}.{fmt}"
    out.unlink(missing_ok=True)
    cmd = [
        exe,
        f"-env:UserInstallation={profile_dir().as_uri()}",
        "--headless",
        "--norestore",
        "--convert-to", fmt,
        "--outdir", str(out_dir),
        str(src),
    ]  # fmt: skip
    with _lock:
        try:
            res = subprocess.run(  # noqa: S603 (our own soffice path + args)
                cmd, capture_output=True, text=True, timeout=timeout_s, check=False
            )
        except subprocess.TimeoutExpired as e:
            raise RenderError(f"LibreOffice timed out after {timeout_s:.0f}s") from e
    if res.returncode != 0 or not out.exists():
        raise RenderError(f"LibreOffice failed ({res.returncode}): {res.stderr.strip()[:300]}")
    return out


def render_pdf(docx: Path, out_dir: Path, timeout_s: float = 180) -> Path:
    return convert(docx, "pdf", out_dir, timeout_s)
