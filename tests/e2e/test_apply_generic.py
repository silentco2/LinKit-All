"""Generic AI form agent inside the apply runner, on a synthetic two-page form. Every request is
intercepted: nothing leaves the machine, and "live" submissions land on fake pages. Needs Google
Chrome installed."""

import asyncio
import re
import sys
from functools import partial
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from playwright.async_api import BrowserContext, Route

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
sys.path.insert(0, str(Path(__file__).parent))
from test_agent_form import FakeAI
from test_matching import fake_embed
from test_tailor import make_cv

from linkit_all.apply import runner
from linkit_all.apply.answers import ApplicationAnswers
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import (
    ActionItem,
    ActionKind,
    ActionStatus,
    Job,
    JobEvent,
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

URL = "https://careers.acme.test/apply"
FIXTURE = Path(__file__).parents[1] / "fixtures/agent/synthetic_two_page.html"
# the fixture's own submit handler swallows the submit; make it a real POST we can intercept
FORM = re.sub(r'onsubmit="[^"]*"', 'method="post" action="/submit"', FIXTURE.read_text("utf-8"))
CONFIRM = "<html><body><h1>Thank you for applying!</h1><p>We have received it.</p></body></html>"
LOGIN = "<html><body><h1>Sign in</h1><input type=password aria-label=Password></body></html>"
CAPTCHA = FORM.replace("<body>", '<body><iframe title="reCAPTCHA challenge" width=200 height=100>')


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
            authorized_countries=["United States", "United Kingdom"],
            needs_sponsorship=False,
            years_experience=3,
        ).model_dump()
        job = Job(source="workable", url=URL, title="Backend Engineer", company="Acme", location="London",
                  description="Python APIs", ats="workable", dedupe_hash="h", score=9, state=JobState.queued_apply,
                  data={"apply_url": URL})  # fmt: skip
        s.add(job)
        s.flush()
        s.add(TailoredCV(job_id=job.id, docx_path=str(cv), pdf_path=str(pdf)))

    state: dict[str, Any] = {"page": FORM, "after_submit": CONFIRM, "posts": []}

    async def handle(route: Route) -> None:
        req = route.request
        if req.method == "POST":
            state["posts"].append(req.url)
            await route.fulfill(body=state["after_submit"], content_type="text/html")
        elif req.url == URL:
            await route.fulfill(body=state["page"], content_type="text/html")
        else:
            await route.abort()

    original = runner.Applier._context

    async def routed(self: runner.Applier, ats: str) -> BrowserContext:
        assert ats == "generic"  # sites without a handler share one persistent profile
        ctx = await original(self, ats)
        if not getattr(ctx, "_test_routed", False):
            await ctx.route("**/*", handle)
            ctx._test_routed = True  # type: ignore[attr-defined]
        return ctx

    monkeypatch.setattr(runner.Applier, "_context", routed)
    # a failed submission would otherwise wait 25 s for a confirmation that never comes
    monkeypatch.setattr(runner, "wait_for_text", partial(runner.wait_for_text, timeout_ms=1500))
    return {"db": db, "settings": settings, "job": job.id, "state": state, "posts": state["posts"]}


def run(env: dict[str, Any], ai: LLMProvider | None = None, **apply: Any) -> dict[str, int]:
    cfg = SearchConfig.model_validate(
        {"apply": {"headless": True, "min_pause_s": 0, "max_pause_s": 0, **apply}}
    )
    return asyncio.run(
        runner.apply_jobs(env["db"], env["settings"], cfg, ai or FakeAI(), fake_embed)
    )


def requeue(env: dict[str, Any], **data: Any) -> None:
    with env["db"].begin() as s:
        job = s.get_one(Job, env["job"])
        job.data = {**job.data, **data}
        for item in s.query(ActionItem).filter_by(job_id=job.id, status=ActionStatus.open):
            item.status = ActionStatus.resolved
        transition(s, job, JobState.queued_apply, "resolved in the Action Center")


def state_of(env: dict[str, Any]) -> JobState:
    with env["db"]() as s:
        return s.get_one(Job, env["job"]).state


def parked(env: dict[str, Any]) -> ActionItem:
    with env["db"]() as s:
        return s.query(ActionItem).one()


def test_dry_run_fills_both_pages_and_never_submits(env: dict[str, Any]) -> None:
    assert run(env)["dry_run"] == 1
    with env["db"]() as s:
        job = s.get_one(Job, env["job"])
        filled = job.data["filled"]
        events = [e.message for e in s.query(JobEvent).filter_by(job_id=job.id)]
    assert job.state == JobState.tailored
    assert filled["Full name"]["value"] == "Jane Doe"  # page 1
    assert any("Why do you want" in k for k in filled)  # page 2
    assert any(m.startswith("dry run: ") and "on 2 pages, not submitted" in m for m in events)
    assert env["posts"] == []
    assert (env["settings"].data_dir / "applications" / f"job_{env['job']}" / "page_2.png").exists()


def test_live_submit_without_asking_applies_only_on_confirmation_text(env: dict[str, Any]) -> None:
    assert run(env, live=True, submit_without_asking=True)["applied"] == 1
    assert len(env["posts"]) == 1
    assert state_of(env) == JobState.applied
    assert (
        env["settings"].data_dir / "applications" / f"job_{env['job']}" / "after_submit.png"
    ).exists()


def test_live_without_confirmation_text_is_failed_never_assumed_applied(
    env: dict[str, Any],
) -> None:
    env["state"]["after_submit"] = "<html><body><p>Thanks.</p></body></html>"
    assert run(env, live=True, submit_without_asking=True)["failed"] == 1
    assert len(env["posts"]) == 1
    assert state_of(env) == JobState.failed


def test_confirmation_text_on_a_page_that_is_still_a_form_is_not_proof(env: dict[str, Any]) -> None:
    env["state"]["after_submit"] = (
        "<html><body><h1>Thank you for applying</h1><input type=text aria-label=Email></body></html>"
    )
    assert run(env, live=True, submit_without_asking=True)["failed"] == 1
    assert state_of(env) == JobState.failed


def test_live_parks_for_confirmation_then_submits_once_confirmed(env: dict[str, Any]) -> None:
    assert run(env, live=True)["needs_user"] == 1
    assert parked(env).kind == ActionKind.confirm_submit
    assert env["posts"] == []
    requeue(env, submit_confirmed=True)
    assert run(env, live=True)["applied"] == 1
    assert len(env["posts"]) == 1
    assert state_of(env) == JobState.applied


def test_sensitive_question_without_an_answer_is_parked(env: dict[str, Any]) -> None:
    with env["db"].begin() as s:
        s.get_one(Profile, 1).answers = ApplicationAnswers(authorized_countries=[]).model_dump()
    ai = FakeAI()
    assert run(env, ai)["needs_user"] == 1
    item = parked(env)
    assert item.kind == ActionKind.unknown_question
    assert [q["sensitive"] for q in item.questions] == [True]
    assert not any("authorized" in q for q in ai.asked)
    assert env["posts"] == []


def test_login_page_parks_login_issue(env: dict[str, Any]) -> None:
    env["state"]["page"] = LOGIN
    assert run(env)["needs_user"] == 1
    item = parked(env)
    assert item.kind == ActionKind.login_issue and "needs an account" in item.message


def test_captcha_parks_captcha(env: dict[str, Any]) -> None:
    env["state"]["page"] = CAPTCHA
    assert run(env)["needs_user"] == 1
    assert parked(env).kind == ActionKind.captcha
    assert env["posts"] == []


def test_generic_agent_off_leaves_such_jobs_alone(env: dict[str, Any]) -> None:
    counts = run(env, generic_agent=False)
    assert sum(counts.values()) == 0
    assert state_of(env) == JobState.queued_apply
