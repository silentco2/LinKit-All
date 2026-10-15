"""Real LibreOffice render + layout check. Skipped where LibreOffice is not installed (CI)."""

from pathlib import Path

import pdfplumber
import pytest
from test_tailor import make_cv, seg_id, texts

from linkit_all.core.config import Settings
from linkit_all.core.tools import soffice_path
from linkit_all.tailor.patches import Patch, Rules, vocabulary
from linkit_all.tailor.pipeline import ensure_base_pdf, tailor_docx

pytestmark = pytest.mark.skipif(soffice_path() is None, reason="LibreOffice not installed")


def test_tailor_with_real_libreoffice_keeps_layout(tmp_path: Path) -> None:
    cv = make_cv(tmp_path / "cv.docx")
    base_pdf = ensure_base_pdf(cv)
    patch = Patch(segment_id=seg_id(cv, "Built"), old_text="scalable", new_text="reliable")
    rules = Rules([], vocabulary(" ".join(texts(cv).values()), []))

    out = tailor_docx(
        cv, base_pdf, [patch], rules, tmp_path / "out", min_ssim=Settings().tailor_min_ssim
    )

    assert out.applied == [patch], out.rejected
    assert out.verify is not None and out.verify.ok, out.verify
    assert out.verify.min_ssim > 0.95  # one-word swap barely moves pixels
    with pdfplumber.open(out.pdf) as pdf:
        text = " ".join((p.extract_text() or "") for p in pdf.pages)
    assert "Built reliable backend" in text
    assert "Skills: Python" in text  # text box survived the round trip
