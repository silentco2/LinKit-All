import shutil
from pathlib import Path

import pymupdf
import pytest

from linkit_all.core.db import init_db
from linkit_all.core.profile import cv_state, save_cv
from linkit_all.core.tools import tectonic_path
from linkit_all.tailor.docx.segments import PatchError
from linkit_all.tailor.latex import LatexError, Segment, apply_patches, load_segments
from linkit_all.tailor.patches import Patch, Rules, plan_patches, vocabulary
from linkit_all.tailor.pipeline import cv_segments, tailor_latex
from linkit_all.tailor.render.latex import render_pdf_latex
from linkit_all.tailor.render.libreoffice import RenderError

FIXTURE = Path(__file__).parent.parent / "fixtures" / "latex" / "cv.tex"
SOURCE = FIXTURE.read_text(encoding="utf-8")


def seg(segments: list[Segment], startswith: str) -> Segment:
    return next(s for s in segments if s.text.startswith(startswith))


def patch(segments: list[Segment], startswith: str, old: str, new: str) -> Patch:
    return Patch(segment_id=seg(segments, startswith).id, old_text=old, new_text=new)


# --- segmentation -------------------------------------------------------------


def test_segments_are_text_only() -> None:
    texts = [s.text for s in load_segments(SOURCE)]
    assert texts[:4] == ["Jane Doe", "Cairo, Egypt", "jane@example.com", "example.com/jane"]
    assert "Built scalable backend services in Python and Go" in texts  # \textbf joined in
    assert "Improved latency by 40% for 2M users; cut R&D costs" in texts  # escapes decoded
    assert (
        "Backend engineer who builds scalable services in Python and Go, with a focus on reliability."
        in texts
    )
    assert "Second paragraph about mentoring junior developers." in texts  # blank line splits
    assert {"Python, Go, SQL", "Docker, Git, PostgreSQL"} <= set(texts)  # tabular cells
    assert {"Languages", "Tools", "Software Engineer, Acme Corp", "2019--2023", "Remote"} <= set(
        texts
    )
    assert "Wrote internal docs for the platform team" in texts  # \item[--] label skipped
    everything = " ".join(texts)
    for hidden in (
        "documentclass",
        "geometry",
        "mailto",
        "https",
        "leftmargin",
        "keep this",
        "not text",
        "log n",
    ):
        assert hidden not in everything
    assert [s.id for s in load_segments(SOURCE)] == list(range(len(texts)))


def test_input_is_rejected() -> None:
    with pytest.raises(LatexError, match="Multi-file"):
        load_segments(SOURCE.replace(r"\section*{Skills}", r"\input{skills}"))
    # in a comment it is harmless
    load_segments(
        SOURCE.replace(r"\section*{Skills}", r"% \input{skills}" + "\n" + r"\section*{Skills}")
    )


# --- patches -------------------------------------------------------------------


def test_patch_changes_only_the_text_span() -> None:
    segments = load_segments(SOURCE)
    p = patch(segments, "Built scalable", "backend", "platform")
    out = apply_patches(SOURCE, segments, [p])
    assert out == SOURCE.replace("scalable} backend services", "scalable} platform services")
    assert [s.text for s in load_segments(out)].count(
        "Built scalable platform services in Python and Go"
    ) == 1


def test_patch_across_markup_keeps_commands() -> None:
    segments = load_segments(SOURCE)
    p = patch(segments, "Built scalable", "Built scalable backend", "Built resilient backend")
    out = apply_patches(SOURCE, segments, [p])
    assert out == SOURCE.replace(r"\textbf{scalable}", r"\textbf{resilient}")


def test_two_patches_one_segment_apply_in_order() -> None:
    segments = load_segments(SOURCE)
    sid = seg(segments, "Built scalable").id
    patches = [
        Patch(segment_id=sid, old_text="backend", new_text="platform"),
        Patch(segment_id=sid, old_text="platform services", new_text="platform systems"),
    ]
    out = apply_patches(SOURCE, segments, patches)
    assert "Built \\textbf{scalable} platform systems in Python and Go" in out


def test_special_characters_are_escaped_and_round_trip() -> None:
    segments = load_segments(SOURCE)
    new = "Mentored devs & ran on-call: 100% #1_team {core}"
    p = patch(
        segments, "Mentored junior", "Mentored junior developers and ran the on-call rota", new
    )
    out = apply_patches(SOURCE, segments, [p])
    assert r"Mentored devs \& ran on-call: 100\% \#1\_team \{core\}" in out
    assert new in [s.text for s in load_segments(out)]


def test_backslash_caret_tilde_refused() -> None:
    segments = load_segments(SOURCE)
    for bad in ("a\\b", "a^b", "a~b"):
        with pytest.raises(PatchError, match="does not write"):
            apply_patches(SOURCE, segments, [patch(segments, "Remote", "Remote", bad)])


def test_bad_patch_shapes() -> None:
    segments = load_segments(SOURCE)
    with pytest.raises(PatchError, match="exactly once"):
        apply_patches(SOURCE, segments, [patch(segments, "Remote", "Nope", "x")])
    with pytest.raises(PatchError, match="unknown segment"):
        apply_patches(SOURCE, segments, [Patch(segment_id=999, old_text="a", new_text="b")])


def test_fixed_space_is_not_editable() -> None:
    src = "\\documentclass{article}\\begin{document}Dr.~Smith leads\\end{document}"
    segments = load_segments(src)
    assert segments[0].text == "Dr. Smith leads"
    with pytest.raises(PatchError, match="fixed space"):
        apply_patches(
            src, segments, [Patch(segment_id=0, old_text="Dr. Smith", new_text="Dr.Smith")]
        )
    out = apply_patches(src, segments, [Patch(segment_id=0, old_text="leads", new_text="guides")])
    assert "Dr.~Smith guides" in out


def test_edit_that_would_merge_into_a_command_is_refused() -> None:
    src = "\\documentclass{article}\\begin{document}\\hfill2020 text\\end{document}"
    segments = load_segments(src)
    assert segments[0].text == "2020 text"
    with pytest.raises(PatchError, match="commands"):
        apply_patches(src, segments, [Patch(segment_id=0, old_text="2020", new_text="Xtra")])


def test_cv_defined_commands_take_text_arguments() -> None:
    src = (
        "\\documentclass{article}\\newcommand{\\job}[2]{#1 #2}\\begin{document}"
        "\\job{Engineer}{Acme}\\setlength{\\parindent}{0pt}\\end{document}"
    )
    assert [s.text for s in load_segments(src)] == ["Engineer", "Acme"]


def test_patch_rules_apply_to_latex_segments() -> None:
    segments = load_segments(SOURCE)
    texts = {s.id: s.text for s in segments}
    rules = Rules(["Acme Corp"], vocabulary(" ".join(texts.values()), ["Python"]))
    wrong = [
        patch(segments, "Improved latency", "40%", "50%"),  # number
        patch(segments, "Software Engineer", "Acme Corp", "Other Corp"),  # locked fact
        patch(segments, "Built scalable", "Python", "Kubernetes"),  # unlisted skill
        patch(segments, "Mentored junior", "Mentored", "Coached"),  # fine
    ]
    plan = plan_patches(texts, wrong, rules)
    assert [p.new_text for p in plan.accepted] == ["Coached"]
    assert len(plan.rejected) == 3


# --- profile upload ------------------------------------------------------------


def test_save_cv_accepts_tex_and_rejects_bad_files(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    cv = save_cv(db, tmp_path, "my cv.tex", SOURCE.encode())
    assert cv.suffix == ".tex" and cv.read_bytes() == SOURCE.encode()
    assert cv_state(db) == ("tex", True)
    assert cv_segments(cv)[0].text == "Jane Doe"
    for bad, msg in [
        (b"\xff\xfe\x00", "UTF-8"),
        (b"just text", "complete LaTeX"),
        (SOURCE.replace(r"\section*{Skills}", r"\input{x}").encode(), "Multi-file"),
    ]:
        with pytest.raises(ValueError, match=msg):
            save_cv(db, tmp_path, "bad.tex", bad)


# --- pipeline (fake renderer) ----------------------------------------------------


def fake_render(src: Path, out_dir: Path) -> Path:
    """Stand-in for Tectonic: one PDF page with each segment's text; "overflow" adds a page."""
    text = src.read_bytes().decode()
    pdf = pymupdf.open()
    page = pdf.new_page()
    for i, s in enumerate(load_segments(text)):
        page.insert_text((50, 60 + 14 * i), s.text, fontsize=9)
    if "overflow" in text:
        pdf.new_page().insert_text((50, 60), "overflow")
    out = out_dir / f"{src.stem}.pdf"
    pdf.save(str(out))
    return out


def tailor(tmp_path: Path, patches: list[Patch]) -> tuple[Path, list[Patch], list[str]]:
    base = tmp_path / "cv.tex"
    base.write_bytes(SOURCE.encode())
    base_pdf = fake_render(base, tmp_path)
    segments = load_segments(SOURCE)
    rules = Rules([], vocabulary(" ".join(s.text for s in segments), []), max_word_change=0.5)
    res = tailor_latex(
        base, base_pdf, patches, rules, tmp_path / "out", min_ssim=0.9, render=fake_render
    )
    assert res.pdf.exists()
    return res.docx, res.applied, [r for _, r in res.rejected]


def test_tailor_latex_applies_patches(tmp_path: Path) -> None:
    segments = load_segments(SOURCE)
    good = patch(segments, "Mentored junior", "Mentored", "Coached")
    out, applied, rejected = tailor(tmp_path, [good])
    assert applied == [good] and not rejected
    assert out.read_bytes().decode() == SOURCE.replace("Mentored junior", "Coached junior")


def test_tailor_latex_rolls_back_on_layout_change(tmp_path: Path) -> None:
    segments = load_segments(SOURCE)
    # "overflow" is a plain word, so the rules accept it, and the fake renderer adds a page.
    grow = patch(segments, "Mentored junior", "junior developers", "overflow")
    out, applied, rejected = tailor(tmp_path, [grow])
    assert applied == [] and "rolled back: page count changed" in rejected[0]
    assert out.read_bytes().decode() == SOURCE  # untouched CV submitted


# --- Tectonic (skipped when not installed) ------------------------------------------


def test_render_without_tectonic_says_how_to_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("linkit_all.tailor.render.latex.tectonic_path", lambda: None)
    with pytest.raises(RenderError, match="Install Tectonic"):
        render_pdf_latex(FIXTURE, FIXTURE.parent)


@pytest.mark.skipif(tectonic_path() is None, reason="tectonic not installed")
def test_tectonic_render_and_verify(tmp_path: Path) -> None:
    base = tmp_path / "cv.tex"
    shutil.copyfile(FIXTURE, base)
    base_pdf = render_pdf_latex(base, tmp_path)
    segments = load_segments(SOURCE)
    rules = Rules([], vocabulary(" ".join(s.text for s in segments), []))
    p = patch(segments, "Mentored junior", "Mentored", "Coached")
    res = tailor_latex(base, base_pdf, [p], rules, tmp_path / "out", min_ssim=0.9)
    assert res.verify is not None and res.verify.ok, res.verify
    assert res.applied == [p]
    assert "Coached junior" in res.docx.read_text(encoding="utf-8")
