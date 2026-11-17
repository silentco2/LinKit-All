"""D1: the finished CV may say nothing the original CV or the locked facts do not."""

import asyncio
import json
from pathlib import Path

import docx
import pymupdf
import pytest

from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobEvent, JobState
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.providers.base import LLMProvider
from linkit_all.tailor.docx.segments import load_segments
from linkit_all.tailor.patches import Patch, Rules, vocabulary
from linkit_all.tailor.pipeline import Renderer, tailor_docx, tailor_job
from linkit_all.tailor.verify.facts import new_facts

CV = """Jane Doe
Engineer at Acme, Jan 2019 - Mar 2023
• Built scalable backend services in Python and Go
• Improved latency by 30% for 2M users
Analyst at Initech, Jun 2016 - Dec 2018
"""
LOCKED = ["Acme", "Initech", "Engineer"]


def test_a_reworded_bullet_passes() -> None:
    new = CV.replace("Built scalable backend services", "Developed reliable backend services")
    assert new_facts(CV, new, LOCKED) == []
    assert new_facts(CV, CV, LOCKED) == []
    # the same text wrapped differently by the renderer is still the same text
    assert new_facts(CV, CV.replace("in Python", "in\nPython"), LOCKED) == []


def test_a_bigger_title_fails() -> None:
    found = new_facts(CV, CV.replace("Engineer at Acme", "Senior Engineer at Acme"), LOCKED)
    assert "senior" in " ".join(found)
    # even when the CV uses the word somewhere else, the title it is put on is new
    cv = CV + "Reported to the Senior Manager\n"
    assert new_facts(cv, cv.replace("Engineer at Acme", "Senior Engineer at Acme"), LOCKED)
    assert new_facts(CV, CV.replace("Analyst at Initech", "Engineer at Initech"), LOCKED)


def test_a_number_the_cv_does_not_have_fails() -> None:
    assert "40%" in new_facts(CV, CV.replace("30%", "40%"), LOCKED)
    assert "40%" in new_facts(CV, CV.replace("Go", "Go, cutting costs 40%"), LOCKED)
    assert new_facts(CV, CV.replace("in Python", "for twelve teams in Python"), LOCKED)


def test_a_moved_date_fails_although_both_words_exist() -> None:
    assert "mar 2019" in new_facts(CV, CV.replace("Jan 2019", "Mar 2019"), LOCKED)
    assert new_facts(CV, CV.replace("Jan 2019", "January 2019"), LOCKED) == []


def test_a_new_employer_or_a_dropped_locked_fact_fails() -> None:
    assert "Globex" in new_facts(CV, CV.replace("at Initech", "at Globex"), LOCKED)
    assert "Acme" in new_facts(CV, CV.replace("Engineer at Acme", "Engineer"), LOCKED)
    assert new_facts(CV, CV.replace("in Python", "in Python for Acme"), LOCKED) == ["Acme"]


def test_a_skill_from_the_profile_is_not_a_new_fact() -> None:
    new = CV.replace("in Python and Go", "in Python, Kubernetes and Go")
    assert new_facts(CV, new, LOCKED) == ["Kubernetes"]
    assert new_facts(CV, new, LOCKED, known={"kubernetes"}) == []


# --- in the pipeline: a rendered CV that says more is rolled back ------------------------------


def _cv(path: Path) -> Path:
    d = docx.Document()
    for line in ("Engineer at Acme, 2019-2023", "Built scalable backend services in Go"):
        d.add_paragraph(line)
    d.save(str(path))
    return path


def _texts(path: Path) -> dict[int, str]:
    return {s.id: s.text for s in load_segments(docx.Document(str(path)))}


def _render(extra: str = "") -> Renderer:
    def render(src: Path, out_dir: Path) -> Path:
        """One PDF page with each segment's text; a tailored file also gets `extra`, as if a
        patch had slipped past the rules."""
        out = pymupdf.open()
        page = out.new_page()
        lines = [t for t in _texts(src).values() if t]
        if src.parent.name.startswith(("out", "job_")):
            lines = [line.replace("Engineer at", f"{extra}Engineer at") for line in lines]
        for i, t in enumerate(lines):
            page.insert_text((50, 60 + 16 * i), t, fontsize=10)
        pdf = out_dir / f"{src.stem}.pdf"
        out.save(str(pdf))
        return pdf

    return render


@pytest.mark.parametrize(("extra", "applied"), [("", 1), ("Senior ", 0)])
def test_tailor_rolls_back_a_cv_that_states_something_new(
    tmp_path: Path, extra: str, applied: int
) -> None:
    cv = _cv(tmp_path / "cv.docx")
    base_pdf = _render()(cv, tmp_path)
    sid = next(i for i, t in _texts(cv).items() if t.startswith("Built"))
    patch = Patch(segment_id=sid, old_text="scalable", new_text="reliable")
    rules = Rules(["Acme"], vocabulary(" ".join(_texts(cv).values()), []))
    out = tailor_docx(
        cv, base_pdf, [patch], rules, tmp_path / "out", min_ssim=0.5, render=_render(extra)
    )
    assert len(out.applied) == applied
    if extra:
        assert "senior engineer" in out.invented
        assert "fact check" in out.rejected[0][1]
        assert out.pdf.read_bytes() == base_pdf.read_bytes()  # the CV as it was is what is sent
    else:
        assert out.invented == []


class _Patches(LLMProvider):
    name = "fake"

    def __init__(self, reply: str) -> None:
        super().__init__("fake")
        self.reply = reply

    async def _call(self, prompt: str) -> str:
        return self.reply


def test_tailor_job_writes_the_fact_check_event(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data", tailor_claim_check=False)
    db = init_db(settings.db_path)
    cv = _cv(tmp_path / "cv.docx")
    import_profile(
        db, ProfileIn(full_name="Jane", email="j@x.io", cv_path=cv, locked_facts=["Acme"]),
        settings.data_dir,
    )  # fmt: skip
    with db.begin() as s:
        job = Job(source="t", url="u", title="Backend", company="Initech", dedupe_hash="h")
        job.state = JobState.queued_apply
        s.add(job)
    sid = next(i for i, t in _texts(cv).items() if t.startswith("Built"))
    reply = json.dumps(
        {"patches": [{"segment_id": sid, "old_text": "scalable", "new_text": "reliable"}]}
    )
    row = asyncio.run(tailor_job(db, job.id, _Patches(reply), settings, render=_render("Senior ")))
    assert row.applied == []
    with db() as s:
        event = s.query(JobEvent).filter_by(job_id=job.id).one()
        assert s.get_one(Job, job.id).state == JobState.tailored
    assert event.code == "tailor_fact_check_failed"
    assert "senior engineer" in event.params["new"]
