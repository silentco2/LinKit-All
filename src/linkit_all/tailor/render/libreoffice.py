"""DOCX -> PDF with LibreOffice headless (the PDF is what gets submitted)."""

import subprocess
import tempfile
import threading
from pathlib import Path

from linkit_all.core.tools import soffice_path

# ponytail: one soffice at a time (instances sharing a profile collide); per-call profiles
# if rendering ever becomes the bottleneck.
_lock = threading.Lock()
_PROFILE = Path(tempfile.gettempdir()) / "linkit-libreoffice-profile"


class RenderError(RuntimeError):
    pass


def render_pdf(docx: Path, out_dir: Path, timeout_s: float = 180) -> Path:
    exe = soffice_path()
    if exe is None:
        raise RenderError("LibreOffice not found; install it and run `linkit doctor`")
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / f"{docx.stem}.pdf"
    pdf.unlink(missing_ok=True)
    cmd = [
        exe,
        f"-env:UserInstallation={_PROFILE.as_uri()}",
        "--headless",
        "--norestore",
        "--convert-to", "pdf",
        "--outdir", str(out_dir),
        str(docx),
    ]  # fmt: skip
    with _lock:
        try:
            res = subprocess.run(  # noqa: S603 (our own soffice path + args)
                cmd, capture_output=True, text=True, timeout=timeout_s, check=False
            )
        except subprocess.TimeoutExpired as e:
            raise RenderError(f"LibreOffice timed out after {timeout_s:.0f}s") from e
    if res.returncode != 0 or not pdf.exists():
        raise RenderError(f"LibreOffice failed ({res.returncode}): {res.stderr.strip()[:300]}")
    return pdf
