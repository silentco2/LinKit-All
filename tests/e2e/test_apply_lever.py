"""Apply flow on a saved Lever form. Every request is intercepted: nothing reaches Lever, and
the "live" submission lands on a fake confirmation page. Needs Google Chrome installed."""

import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from playwright.async_api import BrowserContext, Route

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_matching import fake_embed
from test_tailor import make_cv

from linkit_all.apply import runner
from linkit_all.apply.answers import ApplicationAnswers
from linkit_all.apply.assist import AnswerBank
from linkit_all.apply.handlers import HANDLERS
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import (
    ActionItem,
    ActionKind,
    ActionStatus,
    Job,
    JobState,
    Profile,
    TailoredCV,
)
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.core.tools import chrome_path
from linkit_all.providers.base import LLMProvider

pytestmark = pytest.mark.skipif(chrome_path() is None, reason="Google Chrome not installed")

FORM = (Path(__file__).parents[1] / "fixtures/lever/apply_form.html").read_text("utf-8")
URL = "https://jobs.lever.co/acme/123"
CONFIRM = "<html><body><h3>Application submitted!</h3><p>Thanks for applying.</p></body></html>"


class FakeAI(LLMProvider):
    """First option for choices, a stock sentence for text."""

    name = "fake"

    def __init__(self) -> None:
        super().__init__("fake")

    async def _call(self, prompt: str) -> str:
        if "Write a short cover letter" in prompt:
            return json.dumps({"text": "Dear Hiring Team,\nTest.\nJane"})
        answers = []
        for block in re.split(r"\n- key: ", prompt)[1:]:
            key, kind = block.split(" ", 1)[0], block.split("|")[1].strip()
            opts = re.search(r"\n  options: (.*)", block)
            if opts and "long list" not in opts.group(1):
                first = opts.group(1).split(" || ")[0]
                answer: Any = [first] if kind == "multi" else first
            else:
                answer = False if kind == "checkbox" else "I build backend services in Python."
            answers.append(
                {"key": key, "known": "university" not in block.lower(), "answer": answer}
            )
        return json.dumps({"answers": answers})


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    cv = make_cv(tmp_path / "cv.docx")
    import_profile(db, ProfileIn(full_name="Jane Doe", email="jane@example.com", phone="+44 20 0000 0000",
                                 location="London", cv_path=cv), settings.data_dir)  # fmt: skip
    pdf = tmp_path / "resume.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Jane Doe")
    doc.save(str(pdf))
    with db.begin() as s:
        s.get_one(Profile, 1).answers = ApplicationAnswers(
            authorized_countries=["United Kingdom"], needs_sponsorship=False, years_experience=3
        ).model_dump()
        job = Job(source="lever", url=URL, title="Backend Engineer", company="Acme", location="London",
                  description="Python APIs", ats="lever", dedupe_hash="h", score=9, state=JobState.tailored,
                  data={"apply_url": f"{URL}/apply", "extra": {"board": "acme", "id": "123"}})  # fmt: skip
        s.add(job)
        s.flush()
        s.add(TailoredCV(job_id=job.id, docx_path=str(cv), pdf_path=str(pdf)))

    posts: list[str] = []

    async def handle(route: Route) -> None:
        req = route.request
        if req.method == "POST":
            posts.append(req.url)
            await route.fulfill(body=CONFIRM, content_type="text/html")
        elif req.url.startswith(f"{URL}/apply"):
            await route.fulfill(body=FORM, content_type="text/html")
        else:
            await route.abort()

    original = runner.Applier._context

    async def routed(self: runner.Applier, ats: str) -> BrowserContext:
        ctx = await original(self, ats)
        if not getattr(ctx, "_test_routed", False):
            await ctx.route("**/*", handle)
            ctx._test_routed = True  # type: ignore[attr-defined]
        return ctx

    monkeypatch.setattr(runner.Applier, "_context", routed)
    return {"db": db, "settings": settings, "job": job.id, "posts": posts}


def run(env: dict[str, Any], **apply: Any) -> dict[str, int]:
    cfg = SearchConfig.model_validate(
        {"apply": {"headless": True, "min_pause_s": 0, "max_pause_s": 0, **apply}}
    )
    return asyncio.run(runner.apply_jobs(env["db"], env["settings"], cfg, FakeAI(), fake_embed))


def requeue(env: dict[str, Any], **data: Any) -> None:
    with env["db"].begin() as s:
        job = s.get_one(Job, env["job"])
        job.data = {**job.data, **data}
        for item in s.query(ActionItem).filter_by(job_id=job.id, status=ActionStatus.open):
            item.status = ActionStatus.resolved
        transition(s, job, JobState.queued_apply, "resolved in the Action Center")


def test_lever_dry_run_action_center_confirm_and_submit(env: dict[str, Any]) -> None:
    db = env["db"]

    # 1. Two questions only the user can answer: AI-notetaker consent and the university.
    assert run(env)["needs_user"] == 1
    with db() as s:
        item = s.query(ActionItem).one()
        labels = [q["label"] for q in item.questions]
    assert item.kind == ActionKind.unknown_question
    assert any("notetakers" in label for label in labels) and any(
        "university" in label for label in labels
    )

    # 2. The user answers in the Action Center (saved to the answer bank).
    bank = AnswerBank(db, fake_embed)
    for label in labels:
        bank.save(label, "No, I do not consent" if "notetakers" in label else "Aalborg University", "user",
                  sensitive="notetakers" in label)  # fmt: skip
    requeue(env)

    # 3. Dry run: everything filled, nothing posted.
    assert run(env)["dry_run"] == 1
    with db() as s:
        job = s.get_one(Job, env["job"])
        filled = job.data["filled"]
        assert job.state == JobState.tailored
    assert filled["Full name"]["value"] == "Jane Doe"
    assert filled["Resume/CV"]["value"] == "resume.pdf"
    assert any(v["value"] == "No, I do not consent" for v in filled.values())
    assert not any(
        "marketing" in k.lower() or "future job opportunities" in k for k in filled
    )  # optional consent
    assert env["posts"] == []

    # 4. Live, but each submission waits for the user's click.
    assert run(env, live=True)["needs_user"] == 1
    with db() as s:
        assert s.query(ActionItem).filter_by(kind=ActionKind.confirm_submit).count() == 1
    assert env["posts"] == []

    # 5. Confirmed: submitted once, and "applied" only because the confirmation page said so.
    requeue(env, submit_confirmed=True)
    assert run(env, live=True)["applied"] == 1
    assert len(env["posts"]) == 1
    with db() as s:
        assert s.get_one(Job, env["job"]).state == JobState.applied
    assert (
        env["settings"].data_dir / "applications" / f"job_{env['job']}" / "after_submit.png"
    ).exists()


def test_submit_guard_refuses_in_dry_run() -> None:
    with pytest.raises(runner.DryRunViolation):
        asyncio.run(runner.click_submit(None, HANDLERS["lever"], dry_run=True))  # type: ignore[arg-type]


def test_greenhouse_job_found_through_linkedin_maps_to_its_board() -> None:
    job = Job(id=1, source="linkedin", url="https://linkedin.com/jobs/view/1", title="Dev", company="Acme",
              location="", description="", ats="greenhouse", dedupe_hash="h",
              data={"apply_url": "https://boards.greenhouse.io/acme/jobs/4242?gh_src=li", "extra": {}})  # fmt: skip
    info = runner.job_info(job)
    assert info is not None and info.extra == {"board": "acme", "id": "4242"}
    job.data = {"apply_url": "https://careers.acme.com/jobs/1"}
    assert runner.job_info(job) is None
