"""Account gate on a fake ATS served by request interception: nothing leaves the machine.
Needs Google Chrome installed."""

import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import keyring
import pymupdf
import pytest
from playwright.async_api import BrowserContext, Page, Route

sys.path.insert(0, str(Path(__file__).parents[1] / "unit"))
from test_matching import fake_embed
from test_tailor import make_cv
from test_vault import CHEAP, PASS, MemoryKeyring

from linkit_all.apply import runner
from linkit_all.apply.accounts import (
    KIND,
    Account,
    PasswordRules,
    create_account,
    find_account,
    mark_active,
)
from linkit_all.apply.email_verify import Verification
from linkit_all.apply.handlers import HANDLERS, Handler, JobInfo
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import (
    ActionItem,
    ActionKind,
    Job,
    JobEvent,
    JobState,
    TailoredCV,
)
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.core.search import EmailSection, SearchConfig
from linkit_all.core.tools import chrome_path
from linkit_all.providers.base import LLMProvider

pytestmark = pytest.mark.skipif(chrome_path() is None, reason="Google Chrome not installed")

BASE = "https://fake-ats.test"
EMAIL = "jane@example.com"
PAGE = "<html><body>{}</body></html>"
FORM = PAGE.format(
    """<form id="app-form" action="/submit" method="post"><ul>
<li class="q"><label class="lbl">Full name</label><input type="text" name="name" required></li>
<li class="q"><label class="lbl">Email</label><input type="email" name="email" required></li>
</ul><button id="submit" type="submit">Submit application</button></form>"""
)
SIGNUP = PAGE.format(
    """<form action="/signup" method="post"><input id="email" name="email">
<input id="password" name="password" type="password">
<button id="signup-submit" type="submit">Create account</button></form>"""
)
LOGIN = PAGE.format(
    """<form action="/login" method="post"><input id="email" name="email">
<input id="password" name="password" type="password">
<button id="login-submit" type="submit">Sign in</button></form>"""
)
NEED_LOGIN = PAGE.format("<h1>Please sign in to apply</h1>")
CHECK_EMAIL = PAGE.format("<h1>Check your email</h1>")
VERIFIED = PAGE.format("<h1>Email verified, please sign in</h1>")
TWO_FACTOR = PAGE.format('<h1>Enter your code</h1><input id="otp">')
CONFIRM = PAGE.format("<h3>Application submitted!</h3>")


class FakeATS(Handler):
    ats = "fakeats"
    container = "li.q"
    label = ".lbl"
    submit_button = "#submit"
    confirmation = re.compile("application submitted")
    password_rules = PasswordRules(min_len=12, forbidden="<>&%")

    def form_url(self, job: JobInfo) -> str:
        return f"{BASE}/apply"

    async def open(self, page: Page, job: JobInfo) -> None:
        await page.goto(self.form_url(job), wait_until="domcontentloaded")

    def account_tenant(self, job: JobInfo) -> str | None:
        return "acme"

    def site_domains(self, job: JobInfo) -> list[str]:
        return ["fake-ats.test"]

    async def signed_in(self, page: Page) -> bool:
        return await page.locator("#app-form").count() > 0

    async def two_factor_shown(self, page: Page) -> bool:
        return await page.locator("#otp").count() > 0

    async def _submit_credentials(self, page: Page, path: str, button: str, a: Account) -> None:
        await page.goto(f"{BASE}/{path}", wait_until="domcontentloaded")
        await page.locator("#email").fill(a.username)
        await page.locator("#password").fill(a.password)
        await page.locator(button).click()
        await page.wait_for_load_state("domcontentloaded")

    async def login(self, page: Page, job: JobInfo, account: Account) -> None:
        await self._submit_credentials(page, "login", "#login-submit", account)

    async def signup(self, page: Page, job: JobInfo, account: Account) -> None:
        await self._submit_credentials(page, "signup", "#signup-submit", account)


class FakeAI(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        super().__init__("fake")

    async def _call(self, prompt: str) -> str:
        return '{"answers": []}'


class Site:
    """Server-side state of the fake ATS plus a record of what reached it."""

    def __init__(self) -> None:
        self.signed_in = False
        self.verified = False
        self.two_factor = False
        self.reject_login = False
        self.signups: list[dict[str, list[str]]] = []
        self.logins: list[dict[str, list[str]]] = []
        self.submits: list[str] = []
        self.vault_at_signup: str | None = None  # what the vault held when the POST arrived


@pytest.fixture(autouse=True)
def mem_keyring() -> Any:
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    cv = make_cv(tmp_path / "cv.docx")
    import_profile(db, ProfileIn(full_name="Jane Doe", email=EMAIL, phone="+44 20 0000 0000",
                                 location="London", cv_path=cv), settings.data_dir)  # fmt: skip
    pdf = tmp_path / "resume.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Jane Doe")
    doc.save(str(pdf))
    with db.begin() as s:
        job = Job(source="fakeats", url=f"{BASE}/jobs/1", title="Backend Engineer", company="Acme",
                  location="London", description="Python APIs", ats="fakeats", dedupe_hash="h",
                  score=9, state=JobState.tailored, data={"apply_url": f"{BASE}/apply"})  # fmt: skip
        s.add(job)
        s.flush()
        s.add(TailoredCV(job_id=job.id, docx_path=str(cv), pdf_path=str(pdf)))

    vault = Vault(db, "test-key", kdf=CHEAP)
    vault.create(PASS)
    vault.unlock(PASS)
    vault.put("imap", "imap.gmail.com", EMAIL, "app-password")
    monkeypatch.setattr(runner, "vault_for", lambda _settings, _db: vault)
    monkeypatch.setitem(HANDLERS, "fakeats", FakeATS())

    site = Site()
    mails: list[tuple[Any, ...]] = []
    verification: dict[str, Verification | None] = {
        "result": Verification(link=f"{BASE}/verify?token=t")
    }

    async def fake_wait(*args: Any) -> Verification | None:
        mails.append(args)
        return verification["result"]

    monkeypatch.setattr(runner, "wait_for_verification", fake_wait)

    def stored_password() -> str | None:
        acct = find_account(vault, "fakeats", "acme")
        return acct.password if acct else None

    async def handle(route: Route) -> None:
        req = route.request
        url = urlparse(req.url)
        if url.hostname != "fake-ats.test":
            await route.abort()
            return
        form = parse_qs(req.post_data or "")
        body = NEED_LOGIN
        if req.method == "POST" and url.path == "/signup":
            site.signups.append(form)
            site.vault_at_signup = stored_password()
            body = CHECK_EMAIL
        elif req.method == "POST" and url.path == "/login":
            site.logins.append(form)
            ok = form["password"][0] == stored_password() and site.verified
            if site.reject_login or not ok:
                body = LOGIN
            elif site.two_factor:
                body = TWO_FACTOR
            else:
                site.signed_in = True
                body = FORM
        elif req.method == "POST" and url.path == "/submit":
            site.submits.append(req.url)
            body = CONFIRM
        elif url.path == "/signup":
            body = SIGNUP
        elif url.path == "/login":
            body = LOGIN
        elif url.path == "/verify":
            site.verified = True
            body = VERIFIED
        elif url.path == "/apply" and site.signed_in:
            body = FORM
        await route.fulfill(body=body, content_type="text/html")

    original = runner.Applier._context

    async def routed(self: runner.Applier, ats: str) -> BrowserContext:
        ctx = await original(self, ats)
        if not getattr(ctx, "_test_routed", False):
            await ctx.route("**/*", handle)
            ctx._test_routed = True  # type: ignore[attr-defined]
        return ctx

    monkeypatch.setattr(runner.Applier, "_context", routed)
    return {
        "db": db, "settings": settings, "job": job.id, "vault": vault, "site": site,
        "mails": mails, "verification": verification,
    }  # fmt: skip


def run(env: dict[str, Any], **apply: Any) -> dict[str, int]:
    cfg = SearchConfig.model_validate(
        {"apply": {"headless": True, "min_pause_s": 0, "max_pause_s": 0, **apply}}
    )
    return asyncio.run(runner.apply_jobs(env["db"], env["settings"], cfg, FakeAI(), fake_embed))


def seed_account(env: dict[str, Any], verified: bool = True) -> Account:
    acct = create_account(env["vault"], "fakeats", "acme", EMAIL, FakeATS.password_rules)
    env["site"].verified = verified
    return mark_active(env["vault"], acct, "fakeats", "acme")


def parked(env: dict[str, Any]) -> ActionItem:
    with env["db"]() as s:
        return s.query(ActionItem).filter_by(job_id=env["job"]).one()


def accounts(env: dict[str, Any]) -> list[Any]:
    return [e for e in env["vault"].entries() if e.kind == KIND]


def test_dry_run_without_account_touches_nothing(env: dict[str, Any]) -> None:
    assert run(env)["dry_run"] == 1
    assert env["site"].signups == [] and env["site"].logins == []
    assert accounts(env) == [] and env["mails"] == []
    with env["db"]() as s:
        events = [e.message for e in s.query(JobEvent).filter_by(job_id=env["job"])]
        job = s.get_one(Job, env["job"])
        assert job.state == JobState.tailored
    assert any("would create an account on fakeats (acme)" in m for m in events)


def test_live_signup_saves_password_first_then_verifies_and_fills(env: dict[str, Any]) -> None:
    site = env["site"]
    assert run(env, live=True)["needs_user"] == 1
    assert len(site.signups) == 1
    posted = site.signups[0]["password"][0]
    assert site.vault_at_signup == posted  # already in the vault when the sign-up arrived
    assert not set(posted) & set(FakeATS.password_rules.forbidden)
    assert site.signups[0]["email"] == [EMAIL]
    [entry] = accounts(env)
    assert entry.meta["status"] == "active" and entry.username == EMAIL
    assert env["vault"].get(entry.id) == posted
    assert site.verified and len(site.logins) == 1 and site.logins[0]["password"] == [posted]
    [(cfg, user, pw, domains, since, provider)] = env["mails"]
    assert isinstance(cfg, EmailSection) and (user, pw) == (EMAIL, "app-password")
    assert domains == ["fake-ats.test"] and isinstance(since, datetime) and provider is not None
    item = parked(env)
    assert item.kind == ActionKind.confirm_submit  # form filled, waiting for the user's click
    assert "Full name" in item.answers and site.submits == []


def test_existing_account_logs_in_without_signing_up(env: dict[str, Any]) -> None:
    seed_account(env)
    assert run(env)["dry_run"] == 1  # logging in is fine in a dry run; the form is then filled
    assert len(env["site"].logins) == 1 and env["site"].signups == []
    with env["db"]() as s:
        assert "Full name" in s.get_one(Job, env["job"]).data["filled"]


def test_two_factor_prompt_is_parked(env: dict[str, Any]) -> None:
    seed_account(env)
    env["site"].two_factor = True
    assert run(env, live=True)["needs_user"] == 1
    assert parked(env).kind == ActionKind.two_factor and env["site"].submits == []


def test_rejected_login_is_parked(env: dict[str, Any]) -> None:
    seed_account(env)
    env["site"].reject_login = True
    assert run(env)["needs_user"] == 1
    item = parked(env)
    assert item.kind == ActionKind.login_issue and "rejected" in item.message


def test_locked_vault_is_parked(env: dict[str, Any]) -> None:
    env["vault"].lock()
    assert run(env, live=True)["needs_user"] == 1
    item = parked(env)
    assert item.kind == ActionKind.login_issue and "Unlock" in item.message
    assert env["site"].signups == []


def test_missing_imap_credentials_park_before_signing_up(env: dict[str, Any]) -> None:
    for e in env["vault"].find("imap", "imap.gmail.com"):
        env["vault"].delete(e.id)
    assert run(env, live=True)["needs_user"] == 1
    item = parked(env)
    assert item.kind == ActionKind.login_issue and "Connect your email" in item.message
    assert env["site"].signups == [] and accounts(env) == []


def test_verification_email_never_arrives_is_parked(env: dict[str, Any]) -> None:
    env["verification"]["result"] = None
    assert run(env, live=True)["needs_user"] == 1
    assert parked(env).kind == ActionKind.login_issue
    [entry] = accounts(env)
    assert entry.meta["status"] == "pending_signup"  # kept, so the password isn't lost


def test_signup_guard_refuses_in_dry_run() -> None:
    with pytest.raises(runner.DryRunViolation):
        asyncio.run(
            runner.run_signup(None, FakeATS(), None, None, dry_run=True)  # type: ignore[arg-type]
        )
