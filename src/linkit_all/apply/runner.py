"""Apply stage: tailored CV -> fill the ATS form -> submit only when allowed.

Dry run (the default) fills every field and screenshots it, and never submits. Live
submissions wait for the user's click unless "submit without asking" is on. Success is only
ever recorded from the ATS confirmation page (CLAUDE.md §2, §5.5).
"""

import asyncio
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loguru import logger
from playwright.async_api import BrowserContext, Page, Playwright, async_playwright
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.accounts import (
    Account,
    create_account,
    find_account,
    mark_active,
)
from linkit_all.apply.answers import ApplicationAnswers, Context, Missing, Question
from linkit_all.apply.assist import AnswerBank, answer_questions, profile_summary
from linkit_all.apply.email_verify import EmailLoginError, credentials, wait_for_verification
from linkit_all.apply.form import FillError, fill, lost_values
from linkit_all.apply.handlers import HANDLERS, Handler, JobInfo
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


async def click_submit(page: Page, handler: Handler, dry_run: bool) -> None:
    """The only place the final Submit is clicked. Refuses in dry-run mode."""
    if dry_run:
        raise DryRunViolation("refusing to click Submit in dry-run mode")
    await page.locator(handler.submit_button).locator("visible=true").first.click()


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
    ) -> None:
        self.db, self.settings, self.cfg, self.provider = db, settings, cfg, provider
        self.bank = AnswerBank(db, embed)
        self._pw: Playwright | None = None
        self._contexts: dict[str, BrowserContext] = {}

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
        if ats not in self._contexts:
            if self._pw is None:
                raise RuntimeError("use Applier as an async context manager")
            profile = self.settings.data_dir / "browser" / ats
            profile.mkdir(parents=True, exist_ok=True)
            self._contexts[ats] = await self._pw.chromium.launch_persistent_context(
                str(profile),
                channel="chrome",
                headless=self.cfg.apply.headless,
                viewport={"width": 1280, "height": 900},
            )
        return self._contexts[ats]

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
        jobs = [j for j in jobs if j.ats in HANDLERS and (live or not j.data.get("dry_run_at"))]
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
        if info is None or job.ats not in HANDLERS:
            return Outcome("skipped", f"no form handler for this posting ({job.ats})")
        try:
            cv = await tailor_job(self.db, job_id, self.provider, self.settings)
        except (RenderError, UsageLimitError, TailorError) as e:
            raise ApplyBlocked(str(e)) from e
        with self.db() as s:
            profile = s.get_one(Profile, 1)
        handler = HANDLERS[job.ats]
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
        browser = await self._context(job.ats)
        await browser.tracing.start(screenshots=True, snapshots=True)
        page = await browser.new_page()
        keep_trace = False
        try:
            outcome = await self._fill_and_decide(page, handler, info, ctx, profile, out_dir)
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
        finally:
            trace = out_dir / "trace.zip"
            await browser.tracing.stop(path=str(trace) if keep_trace else None)
            await page.close()

    def _unlocked_vault(self) -> Vault | None:
        vault = vault_for(self.settings, self.db)
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
                msg = f"{site} wants a sign-in code: finish it in the open browser, then retry"
                return await park(ActionKind.two_factor, msg)
            if not await handler.signed_in(page):
                return await park(ActionKind.login_issue, f"{site} rejected the saved login")
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
                    "a CAPTCHA appeared: finish this one by hand",
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
) -> dict[str, int]:
    counts = {"dry_run": 0, "applied": 0, "needs_user": 0, "failed": 0, "skipped": 0}
    async with Applier(db, settings, cfg, provider, embed) as applier:
        job_ids = applier.pick_jobs()
        logger.info("apply: {} jobs ({})", len(job_ids), "live" if cfg.apply.live else "dry run")
        for n, job_id in enumerate(job_ids):
            if n:  # pace between applications, shorter when nothing is submitted
                lo, hi = (
                    (cfg.apply.min_pause_s, cfg.apply.max_pause_s) if cfg.apply.live else (2, 5)
                )
                await asyncio.sleep(random.uniform(lo, max(lo, hi)))  # noqa: S311
            outcome = await applier.apply(job_id)
            counts[outcome.status] += 1
            logger.info("job {}: {} ({})", job_id, outcome.status, outcome.message)
    return counts
