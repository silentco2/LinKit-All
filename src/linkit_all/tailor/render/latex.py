"""Tectonic: LaTeX -> PDF (what gets submitted for a LaTeX CV)."""

import subprocess
from pathlib import Path

from linkit_all.core.tools import tectonic_path
from linkit_all.tailor.render.libreoffice import RenderError


def render_pdf_latex(tex: Path, out_dir: Path, timeout_s: float = 300) -> Path:
    exe = tectonic_path()
    if exe is None:
        raise RenderError(
            "Install Tectonic to tailor LaTeX CVs: https://tectonic-typesetting.github.io"
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{tex.stem}.pdf"
    out.unlink(missing_ok=True)
    # --untrusted: no shell-escape or other insecure features for an uploaded file.
    # First run downloads support files, hence the long timeout.
    cmd = [exe, "-X", "compile", "--untrusted", "--outdir", str(out_dir), str(tex)]
    try:
        res = subprocess.run(  # noqa: S603 (our own tectonic path + args)
            cmd, capture_output=True, text=True, timeout=timeout_s, check=False, cwd=tex.parent
        )
    except subprocess.TimeoutExpired as e:
        raise RenderError(f"Tectonic timed out after {timeout_s:.0f}s") from e
    if res.returncode != 0 or not out.exists():
        raise RenderError(f"Tectonic failed ({res.returncode}): {res.stderr.strip()[-300:]}")
    return out
