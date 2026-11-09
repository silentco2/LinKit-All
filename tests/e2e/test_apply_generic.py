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
EMBED_URL = "https://careers.acme.test/embed"
EMBED_FORM = re.sub(
    r'onsubmit="[^"]*"',
    'method="post" action="/submit"',
    (FIXTURE.parent / "iframe_form.html").read_text("utf-8"),
)
IFRAME_PAGE = (
    (FIXTURE.parent / "iframe_parent.html")
    .read_text("utf-8")
    .replace("__SRC__", EMBED_URL)
    .replace("__HIDDEN__", "about:blank")
)
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

    state: dict[str, Any] = {
        "page": FORM,
        "after_submit": CONFIRM,
        "posts": [],
        "extra": {},
        "seen": [],
    }

    async def handle(route: Route) -> None:
        req = route.request
        state["seen"].append(req.url)
        if req.method == "POST":
            state["posts"].append(req.url)
            await route.fulfill(body=state["after_submit"], content_type="text/html")
        elif req.url == URL:
            await route.fulfill(body=state["page"], content_type="text/html")
        elif req.url in state["extra"]:
            await route.fulfill(body=state["extra"][req.url], content_type="text/html")
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
    monkeypatch.setattr(
        runner, "wait_for_confirmation", partial(runner.wait_for_confirmation, timeout_ms=1500)
    )
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


def test_login_page_in_a_dry_run_only_says_it_would_sign_up(env: dict[str, Any]) -> None:
    env["state"]["page"] = LOGIN
    assert run(env)["dry_run"] == 1
    with env["db"]() as s:
        assert s.query(JobEvent).filter_by(code="dry_run_signup").count() == 1
    assert env["posts"] == []


def google(monkeypatch: pytest.MonkeyPatch, result: str, then: Any = None) -> list[str]:
    calls: list[str] = []

    async def fake(page: Any, email: str) -> str:
        calls.append(email)
        if then is not None:
            then()
        return result

    monkeypatch.setattr(runner, "sign_in_with_google", fake)
    return calls


def test_google_sign_in_goes_back_to_the_form_and_applies(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    env["state"]["page"] = LOGIN
    calls = google(monkeypatch, "signed_in", lambda: env["state"].update(page=FORM))
    got = run(env, live=True, submit_without_asking=True, google_signin=True)
    assert got["applied"] == 1 and calls == ["jane@example.com"] and env["posts"]
    with env["db"]() as s:
        assert s.query(JobEvent).filter_by(code="signed_in_google").count() == 1


def test_google_needs_the_user_and_a_site_that_keeps_asking_parks(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    env["state"]["page"] = LOGIN
    calls = google(monkeypatch, "needs_user")
    assert run(env, live=True, google_signin=True)["needs_user"] == 1
    assert parked(env).code == "google_needed" and len(calls) == 1
    requeue(env)
    google(monkeypatch, "signed_in")  # "signed in", yet the login page is back: one try only
    assert run(env, live=True, google_signin=True)["needs_user"] == 1
    with env["db"]() as s:
        codes = [a.code for a in s.query(ActionItem).order_by(ActionItem.id)]
    assert codes == ["google_needed", "needs_vault"]  # then the account flow: no vault yet


@pytest.mark.parametrize("apply", [{"google_signin": True}, {"live": True}])
def test_no_google_click_in_a_dry_run_or_when_turned_off(
    env: dict[str, Any], monkeypatch: pytest.MonkeyPatch, apply: dict[str, bool]
) -> None:
    env["state"]["page"] = LOGIN
    calls = google(monkeypatch, "signed_in")
    got = run(env, **apply)
    assert calls == []
    if apply.get("live"):
        assert got["needs_user"] == 1 and parked(env).code == "needs_vault"
    else:
        assert got["dry_run"] == 1


def test_captcha_parks_captcha(env: dict[str, Any]) -> None:
    env["state"]["page"] = CAPTCHA
    assert run(env)["needs_user"] == 1
    assert parked(env).kind == ActionKind.captcha
    assert env["posts"] == []


def test_generic_agent_off_leaves_such_jobs_alone(env: dict[str, Any]) -> None:
    counts = run(env, generic_agent=False)
    assert sum(counts.values()) == 0
    assert state_of(env) == JobState.queued_apply


def iframe_site(env: dict[str, Any]) -> None:
    # no controls beside the frame, so the page showing only the confirmation is not a form again
    env["state"]["page"] = re.sub(
        r"<div>\s*<label for=\"referral\".*?</div>", "", IFRAME_PAGE, flags=re.S
    )
    env["state"]["extra"][EMBED_URL] = EMBED_FORM


def test_form_in_an_iframe_is_filled_in_dry_run_without_submitting(env: dict[str, Any]) -> None:
    iframe_site(env)
    assert run(env)["dry_run"] == 1
    assert env["posts"] == []  # dry run never clicks the iframe's Submit
    with env["db"]() as s:
        filled = s.get_one(Job, env["job"]).data["filled"]
    assert filled["Full name"]["value"] == "Jane Doe"


def test_form_in_an_iframe_is_submitted_live_and_confirmed_inside_the_frame(
    env: dict[str, Any],
) -> None:
    iframe_site(env)
    assert run(env, live=True, submit_without_asking=True)["applied"] == 1
    assert len(env["posts"]) == 1  # the Submit inside the frame was clicked, once
    assert state_of(env) == JobState.applied  # the confirmation text is inside the iframe


# --- job ads on boards: press Apply and follow it -----------------------------------------------

BOARD = "https://board.test/jobs/123"
AD = """<html><body><h1>Backend Engineer at Acme</h1><p>Python APIs, remote.</p>
<div role=dialog><p>We use cookies.</p><button type=button onclick="this.parentNode.remove()">Close</button></div>
{apply}</body></html>"""
APPLY_LINK = '<a href="https://careers.acme.test/apply" target=_blank>Apply now</a>'
APPLY_TAB = (
    "<button type=button onclick=\"window.open('https://careers.acme.test/apply')\">Apply</button>"
)


def on_board(env: dict[str, Any], apply_html: str, url: str = BOARD) -> None:
    env["state"]["extra"][url] = AD.format(apply=apply_html)
    with env["db"].begin() as s:
        job = s.get_one(Job, env["job"])
        job.url, job.ats, job.data = url, "board", {**job.data, "apply_url": url}


@pytest.mark.parametrize("apply_html", [APPLY_LINK, APPLY_TAB])
def test_job_ad_apply_leads_to_the_form_which_is_filled(
    env: dict[str, Any], apply_html: str
) -> None:
    on_board(env, apply_html)
    assert run(env)["dry_run"] == 1
    with env["db"]() as s:
        filled = s.get_one(Job, env["job"]).data["filled"]
    assert filled["Full name"]["value"] == "Jane Doe"
    assert env["posts"] == []


def test_apply_leading_to_a_ban_risk_site_parks_for_the_users_own_browser(
    env: dict[str, Any],
) -> None:
    linkedin = "https://www.linkedin.com/jobs/view/1"
    env["state"]["extra"][linkedin] = "<html><body><button>Easy Apply</button></body></html>"
    on_board(env, f'<a href="{linkedin}">Apply on LinkedIn</a>')
    assert run(env)["needs_user"] == 1
    item = parked(env)
    assert item.kind == ActionKind.apply_in_browser and item.code == "apply_in_browser"
    with env["db"]() as s:
        assert s.get_one(Job, env["job"]).data["apply_url"] == linkedin


def test_a_linkedin_job_is_never_driven_by_the_app(env: dict[str, Any]) -> None:
    linkedin = "https://www.linkedin.com/jobs/view/2"
    on_board(env, "", url=linkedin)
    assert run(env)["needs_user"] == 1
    assert parked(env).kind == ActionKind.apply_in_browser
    assert not any("linkedin" in u for u in env["state"]["seen"])  # no page of it was loaded


def test_a_dead_end_is_handed_to_the_user_not_failed(env: dict[str, Any]) -> None:
    env["state"]["page"] = (
        "<html><body><p>This job is advertised in our newsletter.</p></body></html>"
    )
    assert run(env)["needs_user"] == 1
    item = parked(env)
    assert item.kind == ActionKind.apply_by_hand and item.params["why"] == "no_form"


def test_a_job_ad_without_an_apply_button_is_handed_to_the_user(env: dict[str, Any]) -> None:
    on_board(env, "<p>Send your CV to our office.</p><button type=button>Save job</button>")
    assert run(env)["needs_user"] == 1
    assert parked(env).kind == ActionKind.apply_by_hand


# --- accounts on sites without a handler: the app signs up with a vault password -----------------

SIGN_IN = """<html><body><h1>Sign in to apply</h1>
<label>Email <input type=email name=email></label><label>Password <input type=password name=pw></label>
<button type=submit>Sign in</button><a href="/register">Create an account</a></body></html>"""
SIGN_UP = """<html><body><h1>Create your account</h1><form method=post action=/signup>
<label>Full name <input name=name required></label><label>Email <input type=email name=email required></label>
<label>Password <input type=password name=pw required></label><button type=submit>Create account</button>
</form></body></html>"""
VERIFY = "https://careers.acme.test/verify?t=1"


@pytest.fixture
def account_site(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Any:
    from test_vault import CHEAP, PASS

    from linkit_all.apply.email_verify import Verification
    from linkit_all.apply.vault import Vault

    vault = Vault(env["db"], "test-key", kdf=CHEAP)
    vault.create(PASS)
    vault.unlock(PASS)
    vault.put("imap", "imap.gmail.com", "jane@example.com", "app-password")
    monkeypatch.setattr(runner, "vault_for", lambda _settings, _db: vault)
    state = env["state"]
    state["page"] = SIGN_IN
    state["extra"]["https://careers.acme.test/register"] = SIGN_UP
    state["extra"][VERIFY] = "<html><body><p>Your account is verified.</p></body></html>"
    state["after_submit"] = (
        "<html><body><p>Check your email to verify your account.</p></body></html>"
    )

    async def fake_wait(*args: Any) -> Verification:
        state.update(page=FORM, after_submit=CONFIRM)  # the link logs the browser in
        return Verification(link=VERIFY)

    monkeypatch.setattr(runner, "wait_for_verification", fake_wait)
    return vault


def test_live_signs_up_with_a_vault_password_verifies_by_email_then_applies(
    env: dict[str, Any], account_site: Any
) -> None:
    assert run(env, live=True, submit_without_asking=True)["applied"] == 1
    assert len(env["posts"]) == 2  # the sign-up, then the application
    [entry] = [e for e in account_site.entries() if e.kind == "site_account"]
    assert entry.site == "web:careers.acme.test" and entry.username == "jane@example.com"
    assert entry.meta["status"] == "active"
    with env["db"]() as s:
        assert s.query(JobEvent).filter_by(code="account_created").count() == 1


def test_a_saved_login_is_typed_in_and_a_rejected_one_parks(
    env: dict[str, Any], account_site: Any
) -> None:
    from linkit_all.apply.accounts import create_account, mark_active

    acct = create_account(account_site, "web", "careers.acme.test", "jane@example.com",
                          runner.PasswordRules())  # fmt: skip
    mark_active(account_site, acct, "web", "careers.acme.test")
    assert run(env, live=True)["needs_user"] == 1  # the fake site keeps showing its sign-in form
    assert parked(env).code == "login_rejected"
    assert env["posts"] == []  # the sign-in form posts nowhere; no sign-up was tried
