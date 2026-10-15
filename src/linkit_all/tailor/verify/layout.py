"""Check a tailored PDF kept the original layout: page count, SSIM per page, text extracts."""

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pdfplumber
import pymupdf
from skimage.metrics import structural_similarity


@dataclass
class VerifyReport:
    ok: bool
    pages: tuple[int, int]
    min_ssim: float
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _gray(page: pymupdf.Page, dpi: int) -> np.ndarray[Any, np.dtype[np.uint8]]:
    pix = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY, alpha=False)
    rows = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.stride)
    return rows[:, : pix.width]


def verify_pdf(original: Path, tailored: Path, min_ssim: float, dpi: int = 60) -> VerifyReport:
    with pymupdf.open(original) as a, pymupdf.open(tailored) as b:
        pages = (a.page_count, b.page_count)
        if pages[0] != pages[1]:
            return VerifyReport(False, pages, 0.0, f"page count changed {pages[0]} -> {pages[1]}")
        scores = []
        for pa, pb in zip(a, b, strict=True):
            ga, gb = _gray(pa, dpi), _gray(pb, dpi)
            if ga.shape != gb.shape:
                return VerifyReport(False, pages, 0.0, "page size changed")
            scores.append(float(structural_similarity(ga, gb, data_range=255)))
    worst = min(scores, default=1.0)
    with pdfplumber.open(tailored) as pdf:
        has_text = any((p.extract_text() or "").strip() for p in pdf.pages)
    if not has_text:
        return VerifyReport(False, pages, worst, "no extractable text in tailored PDF")
    if worst < min_ssim:
        return VerifyReport(False, pages, worst, f"layout changed (SSIM {worst:.3f} < {min_ssim})")
    return VerifyReport(True, pages, worst)
