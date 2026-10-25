"""Apply stage: tailored CV -> fill the ATS form -> submit only when allowed.

Dry run (the default) fills every field and screenshots it, and never submits. Live
submissions wait for the user's click unless "submit without asking" is on. Success is only
ever recorded from the ATS confirmation page (CLAUDE.md §2, §5.5).
"""

import asyncio
import contextlib
import random
import re
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from loguru import logger
from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
    Playwright,
    async_playwright,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.accounts import (
    Account,
    create_account,
    find_account,
    mark_active,
)
from linkit_all.apply.agent import (
    captcha_shown,
    field_map,
    locate,
    page_errors,
    page_text,
    press_next,
    snapshot,
    step,
    wait_for_confirmation,
)
from linkit_all.apply.answers import ApplicationAnswers, Context, Missing, Question
from linkit_all.apply.assist import AnswerBank, answer_questions, profile_summary
from linkit_all.apply.browser import live_frames, live_shot_path, profile_dir
from linkit_all.apply.email_verify import EmailLoginError, credentials, wait_for_verification
from linkit_all.apply.form import FillError, fill, lost_values
from linkit_all.apply.handlers import HANDLERS, Handler, JobInfo
from linkit_all.apply.handlers.base import GENERIC_CONFIRMATION
from linkit_all.apply.vault import Vault, vault_for
from linkit_all.core.config import Settings
from linkit_all.core.models import (
    ActionItem,
    ActionKind,
    Job,
    JobEvent,
    JobState,
    Profile,
    utcnow,
)
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.matching.rank import Embed, cv_text
from linkit_all.providers.base import LLMProvider, UsageLimitError
from linkit_all.sources.ats_detector import detect
from linkit_all.tailor.pipeline import TailorError, tailor_job
from linkit_all.tailor.render.libreoffice import RenderError


class DryRunViolation(RuntimeError):
    pass


class ApplyBlocked(RuntimeError):
    """Nothing can be applied right now (AI usage limit, LibreOffice missing, no profile).
    Jobs keep their state; the next run continues."""


MAX_AGENT_PAGES = 8


def hand_off(what: str) -> str:
    """Park-message tail: the page is closed after a park, so the user works in the app browser."""
    return (
        f'press "Open in app browser" in the Action Center, {what} there, '
        "close the window, then press Retry"
    )


CAPTCHA_MSG = f"a CAPTCHA appeared: {hand_off('solve it')}"


async def click_submit(page: Page, target: Handler | Locator, dry_run: bool) -> None:
    """The only place the final Submit is clicked: a handler's button, or the generic agent's
    button. Refuses in dry-run mode."""
    if dry_run:
        raise DryRunViolation("refusing to click Submit in dry-run mode")
    if isinstance(target, Handler):
        target = page.locator(target.submit_button).locator("visible=true")
    await target.first.click()


def _web_url(url: str | None) -> bool:
    u = urlparse(url or "")
    return u.scheme in ("http", "https") and bool(u.netloc)


async def _settle(page: Page) -> None:
    """Human pace, then let the next page finish loading (pages that long-poll never go idle)."""
    await asyncio.sleep(random.uniform(0.3, 1.0))  # noqa: S311 (human pace, not crypto)
    with contextlib.suppress(Exception):
        await page.wait_for_load_state("networkidle", timeout=10000)


async def run_signup(
    page: Page, handler: Handler, job: JobInfo, account: Account, dry_run: bool
) -> None:
    """The only place a sign-up form is submitted. Refuses in dry-run mode."""
    if dry_run:
        raise DryRunViolation("refusing to submit a sign-up form in dry-run mode")
    await handler.signup(page, job, account)


@dataclass
class Outcome:
    status: str  # dry_run | applied | needs_user | failed | skipped
    message: str
    artifacts: list[str] = field(default_factory=list)


def job_info(job: Job) -> JobInfo | None:
    """What a handler needs; None if the posting can't be mapped to its ATS form."""
    extra = dict(job.data.get("extra") or {})
    apply_url = job.data.get("apply_url") or job.url
    if job.ats == "greenhouse" and not {"board", "id"} <= extra.keys():
        found = detect(apply_url)  # e.g. a LinkedIn job linking to a Greenhouse board
        gh_id = re.search(r"(?:jobs/|gh_jid=|token=)(\d+)", apply_url)
        if not (found and found[0] == "greenhouse" and gh_id):
            return None
        extra.update(board=found[1], id=gh_id.group(1))
    return JobInfo(
        job.id,
        job.title,
        job.company,
        job.location,
        job.description,
        job.url,
        apply_url,
        job.source,
        extra,
    )


def site_key(job: Job) -> str:
    """What "one site" means for pacing: a handler's ATS (all its boards), else the apply host."""
    if job.ats in HANDLERS:
        return str(job.ats)
    return urlparse(job.data.get("apply_url") or job.url or "").netloc.lower() or "unknown"


def _event(s: Session, job: Job, message: str, artifacts: list[str]) -> None:
    """History entry without a state change (e.g. a dry run)."""
    s.add(
        JobEvent(
            job=job, from_state=job.state, to_state=job.state, message=message, artifacts=artifacts
        )
    )


def _park(
    s: Session,
    job: Job,
    kind: ActionKind,
    message: str,
    questions: list[dict[str, Any]],
    answers: dict[str, Any],
    artifacts: list[str],
) -> None:
    s.add(
        ActionItem(
            job_id=job.id,
            kind=kind,
            message=message,
            questions=questions,
            answers=answers,
            artifacts=artifacts,
        )
    )
    if job.state != JobState.applying:
        transition(s, job, JobState.applying, "filling the application")
    transition(s, job, JobState.needs_user, message, artifacts)


def _missing_dict(m: Missing) -> dict[str, Any]:
    q = m.question
    return {
        "label": q.label,
        "kind": q.kind,
        "options": q.options,
        "required": q.required,
        "reason": m.reason,
        "sensitive": m.sensitive,
    }


def _summary(
    questions: list[Question], answers: dict[str, Any], sources: dict[str, str]
) -> dict[str, Any]:
    """What was filled, for the confirm-before-submit screen (file paths reduced to names)."""
    out = {}
    for q in questions:
        if q.key in answers:
            value = answers[q.key]
            if q.kind == "file":
                value = Path(str(value)).name
            out[q.label or q.key] = {"value": value, "source": sources.get(q.key, "")}
    return out


class Applier:
    def __init__(
        self,
        db: sessionmaker[Session],
        settings: Settings,
        cfg: SearchConfig,
        provider: LLMProvider,
        embed: Embed,
        vault: Vault | None = None,  # the server's shared vault; the CLI passes none
        publish: Callable[[dict[str, Any]], None] | None = None,  # live events; the CLI passes none
    ) -> None:
        self.db, self.settings, self.cfg, self.provider = db, settings, cfg, provider
        self._publish = publish
        self._vault = vault
        self.bank = AnswerBank(db, embed)
        self._pw: Playwright | None = None
        self._contexts: dict[str, BrowserContext] = {}
        self._locks: dict[str, asyncio.Lock] = {}  # per context key: create / trace start+stop
        self._tracing: dict[str, int] = {}  # jobs tracing on each context right now
        self._keep_trace: dict[str, list[Path]] = {}  # out dirs that want the trace saved

    async def __aenter__(self) -> "Applier":
        self._pw = await async_playwright().start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        for ctx in self._contexts.values():
            await ctx.close()
        if self._pw is not None:
            await self._pw.stop()

    async def _context(self, ats: str) -> BrowserContext:
        """One persistent Chrome profile per ATS, so cookies and sessions survive runs."""
        async with self._locks.setdefault(ats, asyncio.Lock()):  # two workers, one launch
            if ats not in self._contexts:
                if self._pw is None:
                    raise RuntimeError("use Applier as an async context manager")
                profile = profile_dir(self.settings, ats)
                profile.mkdir(parents=True, exist_ok=True)
                self._contexts[ats] = await self._pw.chromium.launch_persistent_context(
                    str(profile),
                    channel="chrome",
                    headless=self.cfg.apply.headless,
                    viewport={"width": 1280, "height": 900},
                )
            return self._contexts[ats]

    async def _trace_start(self, key: str, browser: BrowserContext) -> None:
        """Tracing is per context, and jobs on different hosts share the "generic" one: the
        first job starts it, the last one stops it."""
        async with self._locks.setdefault(key, asyncio.Lock()):
            if not self._tracing.get(key):
                await browser.tracing.start(screenshots=True, snapshots=True)
            self._tracing[key] = self._tracing.get(key, 0) + 1

    async def _trace_stop(self, key: str, browser: BrowserContext, keep: Path | None) -> None:
        async with self._locks.setdefault(key, asyncio.Lock()):
            if keep is not None:
                self._keep_trace.setdefault(key, []).append(keep)
            self._tracing[key] -= 1
            if self._tracing[key]:
                return
            dirs = self._keep_trace.pop(key, [])
            first = dirs[0] / "trace.zip" if dirs else None
            await browser.tracing.stop(path=str(first) if first else None)
            for d in dirs[1:]:  # ponytail: overlapping jobs share one trace, copied to each
                if first is not None:
                    shutil.copyfile(first, d / "trace.zip")

    def site_of(self, job_id: int) -> str:
        with self.db() as s:
            return site_key(s.get_one(Job, job_id))

    def pick_jobs(self) -> list[int]:
        """Best-scored jobs ready to apply, within the per-site daily caps."""
        live = self.cfg.apply.live
        since = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        with self.db() as s:
            applied_today = dict(
                s.execute(
                    select(Job.ats, func.count())
                    .join(JobEvent, JobEvent.job_id == Job.id)
                    .where(JobEvent.to_state == JobState.applied, JobEvent.at >= since)
                    .group_by(Job.ats)
                ).all()
            )
            jobs = list(
                s.scalars(
                    select(Job).where(Job.state.in_([JobState.queued_apply, JobState.tailored]))
                )
            )
        generic = self.cfg.apply.generic_agent
        jobs = [
            j
            for j in jobs
            if (j.ats in HANDLERS or (generic and _web_url(j.data.get("apply_url") or j.url)))
            and (live or not j.data.get("dry_run_at"))
        ]
        jobs.sort(key=lambda j: (-(j.score or 0), -(j.data.get("rank") or 0)))
        picked: list[int] = []
        per_site: dict[str, int] = {}
        for j in jobs:
            used = applied_today.get(j.ats, 0) + per_site.get(j.ats or "", 0)
            if live and used >= self.cfg.apply.daily_cap_per_site:
                continue
            per_site[j.ats or ""] = per_site.get(j.ats or "", 0) + 1
            picked.append(j.id)
            if len(picked) >= self.cfg.apply.max_per_run:
                break
        return picked

    async def apply(self, job_id: int) -> Outcome:
        with self.db() as s:  # decide first: never tailor a job we won't apply to (CLAUDE.md §4)
            job = s.get_one(Job, job_id)
            info = job_info(job)
        handler = HANDLERS.get(job.ats or "")
        generic = self.cfg.apply.generic_agent
        if info is None or (handler is None and not (generic and _web_url(info.apply_url))):
            return Outcome("skipped", f"no form handler for this posting ({job.ats})")
        try:
            cv = await tailor_job(self.db, job_id, self.provider, self.settings)
        except (RenderError, UsageLimitError, TailorError) as e:
            raise ApplyBlocked(str(e)) from e
        with self.db() as s:
            profile = s.get_one(Profile, 1)
        out_dir = self.settings.data_dir / "applications" / f"job_{job_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        ctx = Context(
            full_name=profile.full_name,
            email=profile.email,
            phone=profile.phone,
            location=profile.location,
            answers=ApplicationAnswers.model_validate(profile.answers),
            job_location=job.location,
            job_source=job.source,
            resume_path=cv.pdf_path,
        )
        key = handler.ats if handler else "generic"
        browser = await self._context(key)
        await self._trace_start(key, browser)
        page = await browser.new_page()
        # ponytail: pages of parallel sites all write the one current.jpg, latest frame wins
        live = asyncio.create_task(
            live_frames(
                page,
                live_shot_path(self.settings),
                on_frame=lambda: self._announce_frame(job_id, job.title, job.company),
            )
        )
        keep_trace = False
        try:
            if handler is not None:
                outcome = await self._fill_and_decide(page, handler, info, ctx, profile, out_dir)
            else:
                outcome = await self._agent_apply(page, info, ctx, profile, out_dir)
            keep_trace = outcome.status == "failed"
            return outcome
        except UsageLimitError as e:  # before any state change: the job just waits
            raise ApplyBlocked(str(e)) from e
        except Exception as e:
            keep_trace = True
            logger.exception("job {}: apply crashed", job_id)
            with self.db.begin() as s:
                job = s.get_one(Job, job_id)
                if job.state != JobState.applying:
                    transition(s, job, JobState.applying, "filling the application")
                transition(s, job, JobState.failed, f"{type(e).__name__}: {e}")
            return Outcome("failed", str(e))
        except asyncio.CancelledError:  # another site hit ApplyBlocked and stopped this run
            keep_trace = True
            with self.db.begin() as s:
                job = s.get_one(Job, job_id)
                if job.state == JobState.applying:  # may or may not have been submitted
                    transition(s, job, JobState.failed, "run stopped mid-application: check site")
            raise
        finally:
            live.cancel()
            await asyncio.gather(live, return_exceptions=True)  # removes the frame file if last
            await self._trace_stop(key, browser, out_dir if keep_trace else None)
            await page.close()

    def _announce_frame(self, job_id: int, title: str, company: str) -> None:
        """Tell the Live Run screen which job the newest frame shows (no CV text or answers)."""
        if self._publish is not None:
            version = time.time_ns() // 1_000_000
            self._publish(
                {
                    "type": "live_shot",
                    "job_id": job_id,
                    "title": title,
                    "company": company,
                    "version": version,
                    "url": f"/api/live/screenshot?v={version}",
                }
            )

    async def _agent_apply(
        self, page: Page, info: JobInfo, ctx: Context, profile: Profile, out_dir: Path
    ) -> Outcome:
        """A site without a handler: the model maps each page, our code fills and presses.
        Same rules as the handlers: dry run never submits, live waits for the user's confirm
        unless told not to, and "applied" needs a confirmation text on the page."""
        apply_cfg = self.cfg.apply
        live = apply_cfg.live
        await page.goto(info.apply_url or info.url, wait_until="domcontentloaded", timeout=60000)
        await _settle(page)
        brief = {"title": info.title, "company": info.company, "description": info.description}
        cv, summary = cv_text(profile), profile_summary(ctx)
        filled: dict[str, Any] = {}
        shots: list[str] = []

        def park(
            kind: ActionKind,
            message: str,
            questions: list[dict[str, Any]] | None = None,
            answers: dict[str, Any] | None = None,
        ) -> Outcome:
            with self.db.begin() as s:
                job = s.get_one(Job, info.id)
                _park(s, job, kind, message, questions or [], answers or {}, shots[-1:])
            return Outcome("needs_user", message, shots[-1:])

        def fail(reason: str) -> Outcome:
            with self.db.begin() as s:
                job = s.get_one(Job, info.id)
                if job.state != JobState.applying:
                    transition(s, job, JobState.applying, "filling the application")
                transition(s, job, JobState.failed, reason, shots[-1:])
            return Outcome("failed", reason, shots[-1:])

        for n in range(1, MAX_AGENT_PAGES + 1):
            r = await step(
                page, self.provider, ctx, self.bank, cv, summary, brief, out_dir, dry_run=not live
            )
            shots.append(str(out_dir / f"page_{n}.png"))
            await page.screenshot(path=shots[-1], full_page=True)
            filled.update(_summary(r.questions, r.answers, r.sources))
            if await captcha_shown(page):
                return park(ActionKind.captcha, CAPTCHA_MSG)
            if r.page_kind in ("login", "signup"):
                return park(
                    ActionKind.login_issue,
                    f"This site needs an account: {hand_off('sign in')}",
                )
            if r.missing:
                return park(
                    ActionKind.unknown_question,
                    f"{len(r.missing)} question(s) need your answer",
                    [_missing_dict(m) for m in r.missing],
                )
            if r.failed or r.unfilled or r.errors:
                empty = [f"{label}: still empty" for label in r.unfilled]
                problems = [*r.failed.values(), *empty, *r.errors]
                return park(ActionKind.validation_error, "; ".join(problems)[:500], answers=filled)
            if r.action == "stop" or r.button is None:
                return fail(r.reason or "the form agent found no way forward")
            if r.action == "next":
                await press_next(page, r)
                await _settle(page)
                continue

            # r.action == "submit" and nothing on the page is open
            if not live:
                msg = f"{len(filled)} fields filled on {n} pages"
                with self.db.begin() as s:
                    job = s.get_one(Job, info.id)
                    _event(s, job, f"dry run: {msg}, not submitted", shots)
                    job.data = {**job.data, "dry_run_at": utcnow().isoformat(), "filled": filled}
                return Outcome("dry_run", msg, shots)
            with self.db.begin() as s:
                job = s.get_one(Job, info.id)
                if not apply_cfg.submit_without_asking and not job.data.get("submit_confirmed"):
                    message = "ready to submit: check the form and confirm"
                    _park(s, job, ActionKind.confirm_submit, message, [], filled, shots[-1:])
                    return Outcome("needs_user", "waiting for your confirmation", shots[-1:])
                transition(s, job, JobState.applying, "submitting")
            submit = await locate(page, r.button.id)
            await click_submit(page, submit, dry_run=not live)
            done = str(out_dir / "after_submit.png")
            seen = await wait_for_confirmation(page, GENERIC_CONFIRMATION)
            confirmed = seen and not await self._form_again(page)
            await page.screenshot(path=done, full_page=True)
            proof = [shots[-1], done]
            if confirmed:
                with self.db.begin() as s:
                    job = s.get_one(Job, info.id)
                    job.data = {**job.data, "applied_at": utcnow().isoformat(), "filled": filled}
                    transition(s, job, JobState.applied, "confirmation page seen", proof)
                return Outcome("applied", "submitted and confirmed", proof)
            shots.append(done)
            if await captcha_shown(page):
                return park(
                    ActionKind.captcha,
                    CAPTCHA_MSG,
                    answers=filled,
                )
            if errors := await page_errors(page):
                return park(ActionKind.validation_error, "; ".join(errors)[:500], answers=filled)
            return fail("no confirmation page after submitting")
        return fail(f"more than {MAX_AGENT_PAGES} pages: the form agent gave up")

    async def _form_again(self, page: Page) -> bool:
        """Extra check once the confirmation text matched: if the page still has form controls,
        ask the model whether it really is a form. Model unavailable = trust the text."""
        try:
            controls = await snapshot(page)
            if not controls:
                return False
            fmap = await field_map(
                self.provider, controls, await page.title(), await page_text(page)
            )
        except Exception:
            return False
        return fmap.page_kind in ("form", "review", "login", "signup")

    def _unlocked_vault(self) -> Vault | None:
        vault = self._vault if self._vault is not None else vault_for(self.settings, self.db)
        if not vault.unlocked() and vault.initialized():
            vault.unlock_from_keyring()
        return vault if vault.unlocked() else None

    async def _account_gate(
        self, page: Page, handler: Handler, info: JobInfo, profile: Profile, out_dir: Path
    ) -> Outcome | None:
        """Sign in (signing up first when live) if the ATS needs an account. None = signed in."""
        tenant = handler.account_tenant(info)
        if tenant is None or await handler.signed_in(page):
            return None
        site = f"{handler.ats} ({tenant})"
        live = self.cfg.apply.live

        async def park(kind: ActionKind, message: str) -> Outcome:
            shot = str(out_dir / "account.png")
            await page.screenshot(path=shot)
            with self.db.begin() as s:
                _park(s, s.get_one(Job, info.id), kind, message, [], {}, [shot])
            return Outcome("needs_user", message, [shot])

        vault = self._unlocked_vault()
        if vault is None:
            msg = f"Unlock (or create) the vault so the app can sign in to {site}"
            return await park(ActionKind.login_issue, msg)
        account = find_account(vault, handler.ats, tenant)
        if account is None:
            if not live:  # no typing, no clicks: sign-up forms are never touched in a dry run
                msg = f"would create an account on {site}"
                with self.db.begin() as s:
                    job = s.get_one(Job, info.id)
                    _event(s, job, f"dry run: {msg}, not submitted", [])
                    job.data = {**job.data, "dry_run_at": utcnow().isoformat()}
                return Outcome("dry_run", msg)
            mail = credentials(self.cfg.email, vault, profile.email)
            if mail is None:
                msg = "Connect your email in Setup so the app can read the verification email"
                return await park(ActionKind.login_issue, msg)
            account = create_account(  # saved before the sign-up click: a crash never loses it
                vault, handler.ats, tenant, profile.email, handler.password_rules
            )
            since = utcnow()
            await run_signup(page, handler, info, account, dry_run=not live)
            if not await handler.signed_in(page):
                try:
                    found = await wait_for_verification(
                        self.cfg.email, *mail, handler.site_domains(info), since, self.provider
                    )
                except EmailLoginError as e:
                    return await park(ActionKind.login_issue, str(e))
                if found is None or not (found.link or found.code):
                    msg = f"No verification email from {site} arrived in time: check your inbox"
                    return await park(ActionKind.login_issue, msg)
                if found.link:
                    await handler.follow_link(page, found.link)
                elif found.code:
                    await handler.enter_code(page, found.code)
            account = mark_active(vault, account, handler.ats, tenant)
        if not await handler.signed_in(page):
            await handler.login(page, info, account)
            if await handler.two_factor_shown(page):
                msg = f"{site} wants a sign-in code: {hand_off('enter the code')}"
                return await park(ActionKind.two_factor, msg)
            if not await handler.signed_in(page):
                msg = f"{site} rejected the saved login: {hand_off('sign in')}"
                return await park(ActionKind.login_issue, msg)
            if account.status != "active":  # e.g. verified by hand after an earlier timeout
                mark_active(vault, account, handler.ats, tenant)
        await handler.open(page, info)  # back to the application form
        return None

    async def _fill_and_decide(
        self,
        page: Page,
        handler: Handler,
        info: JobInfo,
        ctx: Context,
        profile: Profile,
        out_dir: Path,
    ) -> Outcome:
        apply_cfg = self.cfg.apply
        await handler.open(page, info)
        if (gated := await self._account_gate(page, handler, info, profile, out_dir)) is not None:
            return gated
        questions = await handler.questions(page, info)
        job_brief = {"title": info.title, "company": info.company, "description": info.description}
        r = await answer_questions(
            questions,
            ctx,
            self.bank,
            self.provider,
            cv_text(profile),
            profile_summary(ctx),
            job_brief,
            out_dir,
        )
        shot = str(out_dir / "form.png")
        if r.missing:
            await page.screenshot(path=shot, full_page=True)
            with self.db.begin() as s:
                _park(
                    s,
                    s.get_one(Job, info.id),
                    ActionKind.unknown_question,
                    f"{len(r.missing)} question(s) need your answer",
                    [_missing_dict(m) for m in r.missing],
                    {},
                    [shot],
                )
            return Outcome("needs_user", f"{len(r.missing)} questions need you", [shot])

        failed = []
        for q in questions:
            if q.key in r.answers:
                try:
                    await fill(page, q, r.answers[q.key])
                except FillError as e:
                    if q.required:
                        failed.append(str(e))
                await asyncio.sleep(random.uniform(0.2, 0.7))  # noqa: S311 (human pace, not crypto)
        for q in await lost_values(page, questions, r.answers):  # one refill for reset fields
            try:
                await fill(page, q, r.answers[q.key])
            except FillError as e:
                if q.required:
                    failed.append(str(e))
        await page.screenshot(path=shot, full_page=True)
        filled = _summary(questions, r.answers, r.sources)
        if failed:
            with self.db.begin() as s:
                _park(
                    s,
                    s.get_one(Job, info.id),
                    ActionKind.validation_error,
                    "; ".join(failed)[:500],
                    [],
                    filled,
                    [shot],
                )
            return Outcome("needs_user", "some fields could not be filled", [shot])

        with self.db.begin() as s:
            job = s.get_one(Job, info.id)
            if not apply_cfg.live:
                _event(s, job, f"dry run: {len(filled)} fields filled, not submitted", [shot])
                job.data = {**job.data, "dry_run_at": utcnow().isoformat(), "filled": filled}
                return Outcome("dry_run", f"{len(filled)} fields filled", [shot])
            if not apply_cfg.submit_without_asking and not job.data.get("submit_confirmed"):
                _park(
                    s,
                    job,
                    ActionKind.confirm_submit,
                    "ready to submit: check the form and confirm",
                    [],
                    filled,
                    [shot],
                )
                return Outcome("needs_user", "waiting for your confirmation", [shot])
            transition(s, job, JobState.applying, "submitting")

        await click_submit(page, handler, dry_run=not apply_cfg.live)
        done = str(out_dir / "after_submit.png")
        confirmed = await handler.confirmed(page)
        await page.screenshot(path=done, full_page=True)
        with self.db.begin() as s:
            job = s.get_one(Job, info.id)
            if confirmed:
                job.data = {**job.data, "applied_at": utcnow().isoformat(), "filled": filled}
                transition(s, job, JobState.applied, "confirmation page seen", [shot, done])
                return Outcome("applied", "submitted and confirmed", [shot, done])
            if await handler.captcha_shown(page):
                _park(
                    s,
                    job,
                    ActionKind.captcha,
                    CAPTCHA_MSG,
                    [],
                    filled,
                    [done],
                )
                return Outcome("needs_user", "captcha", [done])
            if errors := await handler.errors(page):
                _park(
                    s, job, ActionKind.validation_error, "; ".join(errors)[:500], [], filled, [done]
                )
                return Outcome("needs_user", "the form rejected some answers", [done])
            transition(
                s, job, JobState.failed, "no confirmation page after submitting", [shot, done]
            )
            return Outcome("failed", "no confirmation seen", [shot, done])


async def apply_jobs(
    db: sessionmaker[Session],
    settings: Settings,
    cfg: SearchConfig,
    provider: LLMProvider,
    embed: Embed,
    vault: Vault | None = None,
    publish: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, int]:
    """Different sites in parallel (up to `parallel_sites`); on one site, one job at a time with
    a random pause between two of them (shorter when nothing is submitted)."""
    counts = {"dry_run": 0, "applied": 0, "needs_user": 0, "failed": 0, "skipped": 0}
    live = cfg.apply.live
    lo, hi = (cfg.apply.min_pause_s, cfg.apply.max_pause_s) if live else (2, 5)
    async with Applier(db, settings, cfg, provider, embed, vault, publish) as applier:
        sites: dict[str, list[int]] = {}  # best-scored site first; jobs keep pick order
        for job_id in applier.pick_jobs():
            sites.setdefault(applier.site_of(job_id), []).append(job_id)
        parallel = cfg.apply.parallel_sites
        logger.info(
            "apply: {} jobs on {} sites, {} at a time ({}) [{}]",
            sum(map(len, sites.values())),
            len(sites),
            parallel,
            "live" if live else "dry run",
            ", ".join(f"{site}: {len(ids)}" for site, ids in sites.items()),
        )
        running = asyncio.Semaphore(parallel)

        async def work(ids: list[int]) -> None:
            async with running:
                for n, job_id in enumerate(ids):
                    if n:  # pace between two applications on the same site
                        await asyncio.sleep(random.uniform(lo, max(lo, hi)))  # noqa: S311
                    outcome = await applier.apply(job_id)
                    counts[outcome.status] += 1  # no await in between: no race
                    logger.info("job {}: {} ({})", job_id, outcome.status, outcome.message)

        try:
            async with asyncio.TaskGroup() as tg:
                for ids in sites.values():
                    tg.create_task(work(ids))
        except BaseExceptionGroup as group:
            blocked, _ = group.split(ApplyBlocked)
            if blocked is not None:  # the run pauses, as with a single worker
                raise blocked.exceptions[0] from None
            raise group
    return counts
