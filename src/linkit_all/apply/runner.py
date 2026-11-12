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
from datetime import datetime
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
    PasswordRules,
    create_account,
    find_account,
    mark_active,
)
from linkit_all.apply.agent import (
    captcha_shown,
    enter_code,
    field_map,
    locate,
    login_form,
    open_signup,
    page_errors,
    page_text,
    press_apply,
    press_next,
    sign_in,
    signup_link_needed,
    snapshot,
    step,
    wait_for_confirmation,
)
from linkit_all.apply.answers import (
    ApplicationAnswers,
    Context,
    Missing,
    Question,
    reason_code,
)
from linkit_all.apply.assist import (
    AnswerBank,
    answer_questions,
    profile_summary,
    remember_bank_secrets,
)
from linkit_all.apply.browser import live_frames, live_shot_path, profile_dir
from linkit_all.apply.email_apply import (
    attachment_copy,
    compose,
    is_mailto,
    mailto_address,
)
from linkit_all.apply.email_send import (
    NoCredentials,
    OutgoingEmail,
    SmtpError,
    build_message,
    save_eml,
    send,
    valid_address,
)
from linkit_all.apply.email_verify import EmailLoginError, credentials, wait_for_verification
from linkit_all.apply.form import FillError, fill, lost_values
from linkit_all.apply.google_signin import sign_in_with_google
from linkit_all.apply.handlers import HANDLERS, Handler, JobInfo
from linkit_all.apply.handlers.base import GENERIC_CONFIRMATION
from linkit_all.apply.vault import Vault, vault_for
from linkit_all.core.chrome import RunningChrome, open_context
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
from linkit_all.sources import registry
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Source
from linkit_all.sources.http import Http, make_client
from linkit_all.sources.jobspy_sites import linkedin_apply
from linkit_all.tailor.pipeline import TailorError, cv_plan, original_cv, tailor_job
from linkit_all.tailor.render.libreoffice import RenderError


class DryRunViolation(RuntimeError):
    pass


class ApplyBlocked(RuntimeError):
    """Nothing can be applied right now (AI usage limit, LibreOffice missing, no profile).
    Jobs keep their state; the next run continues. With a `code` (and `params`) the run is
    *paused* with that reason, without one it fails."""

    def __init__(
        self, message: str, code: str | None = None, params: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code, self.params = code, params or {}


def usage_blocked(e: UsageLimitError) -> ApplyBlocked:
    return ApplyBlocked(e.message, "ai_usage_limit", {"provider": e.provider, "until": e.until})


NEEDS_TOOL = {
    "needs_libreoffice": "Tailoring needs LibreOffice. Install it (one click), or choose to send "
    "your CV as it is",
    "needs_tectonic": "Your CV is a LaTeX file and needs Tectonic to make the PDF: run "
    "`linkit doctor` to see how to install it",
}


MAX_AGENT_PAGES = 8
MAX_APPLY_HOPS = 3  # job ad -> Apply -> maybe another ad or a redirect page -> the form
APPLY_REDIRECT_WAIT_S = 20.0  # longest we watch for a board's delayed script redirect after Apply


def assisted(url: str | None, hosts: list[str]) -> bool:
    """A ban-risk site (LinkedIn, Indeed, Glassdoor): the app never drives it, the user applies in
    their own browser. Matched on the site's name, so every country domain counts."""
    labels = urlparse(url or "").netloc.lower().split(".")
    return any(h.lower().split(".")[0] in labels for h in hosts)


def job_context(profile: Profile, job: Job, resume_path: str = "") -> Context:
    """What the answer engine knows when applying to `job` (profile facts, job place)."""
    return Context(
        full_name=profile.full_name,
        email=profile.email,
        phone=profile.phone,
        location=profile.location,
        answers=ApplicationAnswers.model_validate(profile.answers),
        address=profile.address,
        postal_code=profile.postal_code,
        home_city=profile.home_city,
        home_state=profile.home_state,
        home_country=profile.home_country,
        job_location=job.location,
        job_source=job.source,
        resume_path=resume_path,
    )


def _fields(controls: list[Any]) -> list[Any]:
    """Controls that take an answer (not buttons or links)."""
    return [c for c in controls if c.kind not in ("button", "link")]


BY_HAND_MSG = (
    'the app could not finish this application on its own: press "Open in my browser", apply '
    'there, then press "I applied"'
)
OFFSITE_MSG = (
    'LinkedIn links this job to the employer\'s own site: press "Open in my browser", press Apply '
    'on LinkedIn, then on the employer\'s form press "Fill this step" in the LinkIt panel'
)
IN_BROWSER_MSG = (
    'this site bans automated applying, so apply in your own browser: press "Open in my '
    'browser" (the LinkIt extension fills the form), then press Next and Submit yourself'
)


def hand_off(what: str) -> str:
    """Park-message tail: the page is closed after a park, so the user works in the app browser."""
    return (
        f'press "Open in app browser" in the Action Center, {what} there, '
        "close the window, then press Retry"
    )


CAPTCHA_MSG = f"a CAPTCHA appeared: {hand_off('solve it')}"
# the page after a sign-up click asks for the emailed link or code
VERIFY_PAGE = re.compile(r"verif|confirm (your )?e-?mail|check your (e-?mail|inbox)|\bcode\b", re.I)
WEB = "web"  # vault "ats" of accounts on sites without a handler; the tenant is the host


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


def is_pickable(j: Job, generic: bool, live: bool) -> bool:
    """Whether the next apply stage would take this queued/tailored job (before daily caps)."""
    return bool(
        (
            mailto_address(j.data.get("apply_url"))
            or j.ats in HANDLERS
            or (generic and _web_url(j.data.get("apply_url") or j.url))
        )
        and (live or not j.data.get("dry_run_at"))
        and not j.data.get("mail_sending")  # LinkIt mail is sending it right now
    )


def emails_sent_today(s: Session) -> int:
    since = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return (
        s.scalar(
            select(func.count())
            .select_from(JobEvent)
            .where(JobEvent.code == "applied_by_email", JobEvent.at >= since)
        )
        or 0
    )


def emailed(s: Session, addr: str, but: int | None = None) -> Job | None:
    """The applied job whose application email went to `addr` (never the same address twice)."""
    return next(
        (
            o for o in s.scalars(select(Job).where(Job.state == JobState.applied, Job.id != but))
            if (o.data.get("email_sent") or {}).get("to", "").lower() == addr.lower()
        ),
        None,
    )  # fmt: skip


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


async def _where(page: Page) -> tuple[str, int]:
    return page.url.split("#")[0], len(_fields(await snapshot(page)))


async def _moved_on(page: Page, before: tuple[str, int]) -> bool:
    """Apply led somewhere. Boards like RemoteOK redirect from a script, seconds later, so the
    page is watched for a while. A half-loaded page looks different: it must differ once settled."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + APPLY_REDIRECT_WAIT_S
    while True:
        if await _where(page) != before:
            await _settle(page)
            if await _where(page) != before:
                return True
        if loop.time() >= deadline:
            return False
        await asyncio.sleep(0.5)


@dataclass
class Outcome:
    status: str  # dry_run | applied | needs_user | failed | skipped
    message: str
    artifacts: list[str] = field(default_factory=list)
    reason: str = ""  # stable code for an outcome that leaves no job event (else the last event's)


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
    if mailto_address(job.data.get("apply_url")):
        return "email"  # one worker, so emails go out one at a time with a pause between
    if job.ats in HANDLERS:
        return str(job.ats)
    return urlparse(job.data.get("apply_url") or job.url or "").netloc.lower() or "unknown"


def _event(
    s: Session,
    job: Job,
    message: str,
    artifacts: list[str],
    code: str | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    """History entry without a state change (e.g. a dry run). `code`/`params` let the UI show
    the message in the user's language; the English `message` stays for the CLI and logs."""
    s.add(
        JobEvent(
            job=job,
            from_state=job.state,
            to_state=job.state,
            message=message,
            code=code,
            params=params or {},
            artifacts=artifacts,
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
    code: str,
    params: dict[str, Any] | None = None,
) -> None:
    params = params or {}
    s.add(
        ActionItem(
            job_id=job.id,
            kind=kind,
            message=message,
            code=code,
            params=params,
            questions=questions,
            answers=answers,
            artifacts=artifacts,
        )
    )
    if job.state != JobState.applying:
        transition(s, job, JobState.applying, "filling the application", code="filling")
    transition(s, job, JobState.needs_user, message, artifacts, code, params)


def _missing_dict(m: Missing) -> dict[str, Any]:
    q = m.question
    return {
        "label": q.label,
        "kind": q.kind,
        "options": q.options,
        "required": q.required,
        "reason": m.reason,
        "reason_code": reason_code(m.reason)[0],  # not_in_profile | own_answer | ...
        "reason_params": reason_code(m.reason)[1],
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
        http: Http | None = None,  # liveness checks; tests pass a mock-transport client
    ) -> None:
        self.db, self.settings, self.cfg, self.provider = db, settings, cfg, provider
        self._http = http
        self._sources: dict[str, Source] | None = None
        self._publish = publish
        self._vault = vault
        self.bank = AnswerBank(db, embed)
        self._pw: Playwright | None = None
        self._contexts: dict[str, BrowserContext] = {}
        self._chromes: dict[str, RunningChrome] = {}  # the Chrome process behind each context
        self._locks: dict[str, asyncio.Lock] = {}  # per context key: create / trace start+stop
        self._tracing: dict[str, int] = {}  # jobs tracing on each context right now
        self._keep_trace: dict[str, list[Path]] = {}  # out dirs that want the trace saved

    async def __aenter__(self) -> "Applier":
        self._pw = await async_playwright().start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        try:
            for chrome in self._chromes.values():  # ends Chrome; the CDP connection drops with it
                with contextlib.suppress(Exception):
                    await chrome.close()
        finally:
            self._chromes.clear()
            self._contexts.clear()
            if self._pw is not None:
                await self._pw.stop()

    async def _context(self, ats: str) -> BrowserContext:
        """One persistent Chrome profile per ATS, so cookies and sessions survive runs."""
        async with self._locks.setdefault(ats, asyncio.Lock()):  # two workers, one launch
            if ats not in self._contexts:
                if self._pw is None:
                    raise RuntimeError("use Applier as an async context manager")
                profile = profile_dir(self.settings, ats)
                chrome, ctx = await open_context(
                    self._pw, profile, headless=self.cfg.apply.headless
                )
                self._chromes[ats], self._contexts[ats] = chrome, ctx
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
            emails_today = emails_sent_today(s)
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
        jobs = [j for j in jobs if is_pickable(j, generic, live)]
        jobs.sort(key=lambda j: (-(j.score or 0), -(j.data.get("rank") or 0)))
        picked: list[int] = []
        per_site: dict[str, int] = {}
        held: dict[int, dict[str, Any]] = {}  # job id -> why it waits for tomorrow
        for j in jobs:
            by_email = mailto_address(j.data.get("apply_url")) is not None
            key = "email" if by_email else j.ats or ""
            done = (emails_today or 0) if by_email else applied_today.get(j.ats, 0)
            cap = self.cfg.apply.email_daily_cap if by_email else self.cfg.apply.daily_cap_per_site
            if live and done + per_site.get(key, 0) >= cap:
                held[j.id] = {"site": "email" if by_email else j.ats or "", "cap": cap}
                continue
            if len(picked) >= self.cfg.apply.max_per_run:
                continue  # over this run's limit, not the day's: no event
            per_site[key] = per_site.get(key, 0) + 1
            picked.append(j.id)
        if held:
            self._note_daily_cap(held, since)
        return picked

    def _note_daily_cap(self, held: dict[int, dict[str, Any]], since: datetime) -> None:
        """One `daily_cap` history line per held job per day, so the job says why it waits."""
        with self.db.begin() as s:
            noted = set(
                s.scalars(
                    select(JobEvent.job_id).where(
                        JobEvent.code == "daily_cap",
                        JobEvent.at >= since,
                        JobEvent.job_id.in_(held),
                    )
                )
            )
            for job_id, params in held.items():
                if job_id in noted:
                    continue
                job = s.get_one(Job, job_id)
                msg = f"Daily limit on {params['site']} ({params['cap']}): waits for tomorrow"
                _event(s, job, msg, [], code="daily_cap", params=params)

    async def _posting_closed(self, job: Job, info: JobInfo) -> bool:
        """Ask the job's ATS plugin whether the posting still exists. Only a clear "gone" counts;
        an unknown ATS, a network error or any odd answer means carry on. Marks the job skipped."""
        if not job.ats:
            return False
        try:
            if self._sources is None:
                self._sources = registry()
            source = self._sources.get(job.ats)
            if source is None:
                return False
            stub = JobStub(
                source=job.source,
                url=job.url,
                title=job.title,
                company=job.company,
                ats=job.ats,
                extra=info.extra,
            )
            if self._http is not None:
                live = await source.is_live(self._http, stub)
            else:
                async with make_client() as client:
                    live = await source.is_live(Http(client), stub)
        except Exception as e:  # our own failure never blocks an application
            logger.bind(
                code="liveness_check_failed", params={"job": job.id, "error": type(e).__name__}
            ).warning("job {}: liveness check failed: {}", job.id, e)
            return False
        if live is not False:
            return False
        with self.db.begin() as s:
            row = s.get_one(Job, job.id)
            transition(
                s,
                row,
                JobState.skipped,
                f"The posting is no longer open on {job.ats}",
                code="job_closed",
                params={"ats": job.ats},
            )
        return True

    async def _cv_pdf(self, job_id: int, tailor: bool = True) -> str:
        """The CV file this application sends. A tailored PDF, or (`tailor` False, user declined
        tailoring, or practice mode without LibreOffice) the CV as uploaded, with no AI call at
        all. Never an untailored CV when tailoring was chosen and the tool is there."""
        with self.db() as s:
            profile = s.get(Profile, 1)
            fmt = profile.cv_source_format if profile else "docx"
        plan = cv_plan(fmt, self.cfg.apply.tailor_cv if tailor else False, self.cfg.apply.live)
        if plan.mode == "blocked":
            raise ApplyBlocked(NEEDS_TOOL[plan.reason], plan.reason)
        try:
            if plan.mode == "tailor":
                return (await tailor_job(self.db, job_id, self.provider, self.settings)).pdf_path
            if profile is None:
                raise TailorError("No profile yet: run `linkit profile import profile.json`")
            path = await asyncio.to_thread(original_cv, profile)
        except UsageLimitError as e:
            raise usage_blocked(e) from e
        except (RenderError, TailorError) as e:
            raise ApplyBlocked(str(e)) from e
        with self.db.begin() as s:
            transition(
                s, s.get_one(Job, job_id), JobState.tailored,
                "using your CV as it is (not tailored)",
                code="tailor_skipped", params={"reason": plan.reason},
            )  # fmt: skip
        return str(path)

    async def apply(self, job_id: int) -> Outcome:
        with self.db() as s:  # decide first: never tailor a job we won't apply to (CLAUDE.md §4)
            job = s.get_one(Job, job_id)
            info = job_info(job)
        if is_mailto(job.data.get("apply_url")):
            addr = mailto_address(job.data.get("apply_url"))
            if addr is None:
                return Outcome(
                    "skipped",
                    "the apply link is not a single valid email address",
                    reason="bad_email",
                )
            return await self._apply_email(job_id, addr)
        handler = HANDLERS.get(job.ats or "")
        generic = self.cfg.apply.generic_agent
        if info is None or (handler is None and not (generic and _web_url(info.apply_url))):
            return Outcome(
                "skipped", f"no form handler for this posting ({job.ats})", reason="no_handler"
            )
        if await self._posting_closed(job, info):  # a read-only check; costs no AI
            return Outcome("skipped", f"the posting is no longer open on {job.ats}")
        cv_pdf = await self._cv_pdf(job_id)
        with self.db.begin() as s:  # the file the LinkIt extension uploads if the user takes over
            row = s.get_one(Job, job_id)
            row.data = {**row.data, "cv_pdf": cv_pdf}
        if handler is None and assisted(info.apply_url, self.cfg.apply.assisted_hosts):
            return await self._park_in_browser(job_id, info.apply_url)
        with self.db() as s:
            profile = s.get_one(Profile, 1)
        out_dir = self.settings.data_dir / "applications" / f"job_{job_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        ctx = job_context(profile, job, cv_pdf)
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
            raise usage_blocked(e) from e
        except Exception as e:
            keep_trace = True
            logger.bind(
                code="apply_crashed",
                params={"job": job_id, "error": f"{type(e).__name__}: {str(e)[:120]}"},
            ).exception("job {}: apply crashed", job_id)
            with self.db.begin() as s:
                job = s.get_one(Job, job_id)
                if job.state != JobState.applying:
                    transition(s, job, JobState.applying, "filling the application", code="filling")
                transition(
                    s, job, JobState.failed, f"{type(e).__name__}: {e}",
                    code="apply_crashed", params={"error": type(e).__name__},
                )  # fmt: skip
            return Outcome("failed", str(e))
        except asyncio.CancelledError:  # another site hit ApplyBlocked and stopped this run
            keep_trace = True
            with self.db.begin() as s:
                job = s.get_one(Job, job_id)
                if job.state == JobState.applying:  # may or may not have been submitted
                    transition(
                        s,
                        job,
                        JobState.failed,
                        "run stopped mid-application: check site",
                        code="run_stopped",
                    )
            raise
        finally:
            live.cancel()
            await asyncio.gather(live, return_exceptions=True)  # removes the frame file if last
            await self._trace_stop(key, browser, out_dir if keep_trace else None)
            await page.close()

    async def _park_in_browser(
        self, job_id: int, url: str, answers: dict[str, Any] | None = None
    ) -> Outcome:
        """Hand a ban-risk site to the user's own browser (the extension fills it there). For
        LinkedIn, its public page says whether this is Easy Apply or a link to the employer."""
        how = await self._linkedin_kind(url)
        offsite = how == "offsite"
        msg, code = (
            (OFFSITE_MSG, "apply_in_browser_offsite")
            if offsite
            else (IN_BROWSER_MSG, "apply_in_browser")
        )
        with self.db.begin() as s:
            job = s.get_one(Job, job_id)
            job.data = {**job.data, "apply_url": url, **({"linkedin_apply": how} if how else {})}
            _park(
                s, job, ActionKind.apply_in_browser, msg, [], answers or {}, [], code,
                {"site": urlparse(url).netloc},
            )  # fmt: skip
        return Outcome("needs_user", "waiting for you to apply in your browser")

    async def _linkedin_kind(self, url: str) -> str | None:
        """ "offsite" or "easy_apply" from LinkedIn's public job page (one plain GET, no login,
        what any visitor's browser fetches); None for other sites or when it cannot be read."""
        if "linkedin" not in urlparse(url).netloc.lower().split("."):
            return None
        try:
            if self._http is not None:
                return linkedin_apply((await self._http.get(url)).text)
            async with make_client() as client:
                return linkedin_apply((await Http(client).get(url)).text)
        except Exception as e:  # offline, blocked or changed: the card stays generic
            logger.debug("LinkedIn apply kind unknown for {}: {}", url, e)
            return None

    async def _apply_email(self, job_id: int, addr: str) -> Outcome:
        """A `mailto:` posting: the CV as uploaded + short cover email. Dry run only writes an .eml;
        live waits for the user's confirm (draft editable) unless told not to. Sent = applied."""
        apply_cfg = self.cfg.apply
        with self.db() as s:
            already = emailed(s, addr, but=job_id) is not None
        if already:
            with self.db.begin() as s:
                transition(
                    s,
                    s.get_one(Job, job_id),
                    JobState.skipped,
                    f"An application was already emailed to {addr}",
                    code="email_already_sent",
                    params={"to": addr},
                )
            return Outcome("skipped", f"already emailed {addr}")
        cv_pdf = await self._cv_pdf(job_id, tailor=False)  # the AI writes the message, nothing else
        with self.db() as s:
            job = s.get_one(Job, job_id)
            profile = s.get_one(Profile, 1)
        out_dir = self.settings.data_dir / "applications" / f"job_{job_id}"
        out_dir.mkdir(parents=True, exist_ok=True)
        answers = ApplicationAnswers.model_validate(profile.answers)

        def fail(reason: str, params: dict[str, Any]) -> Outcome:
            with self.db.begin() as s:
                row = s.get_one(Job, job_id)
                if row.state != JobState.applying:
                    transition(s, row, JobState.applying, "sending the email", code="submitting")
                transition(s, row, JobState.failed, reason, code="email_failed", params=params)
            return Outcome("failed", reason)

        def park(kind: ActionKind, message: str, code: str, params: dict[str, Any]) -> Outcome:
            with self.db.begin() as s:
                _park(s, s.get_one(Job, job_id), kind, message, [], {}, [], code, params)
            return Outcome("needs_user", message)

        draft = job.data.get("email_draft")
        if not (isinstance(draft, dict) and draft.get("to") == addr and draft.get("attachment")):
            draft = None  # nothing usable saved yet (or the address changed)
        if draft is None:
            ctx = Context(
                full_name=profile.full_name,
                email=profile.email,
                phone=profile.phone,
                location=profile.location,
                answers=answers,
                job_location=job.location,
                job_source=job.source,
                resume_path=cv_pdf,
            )
            try:
                made = await compose(
                    self.provider,
                    to=addr,
                    job={
                        "title": job.title,
                        "company": job.company,
                        "description": job.description,
                    },
                    cv=cv_text(profile),
                    profile_facts=profile_summary(ctx),
                    full_name=profile.full_name,
                    phone=profile.phone,
                    linkedin=answers.linkedin,
                    author=(job.data.get("extra") or {}).get("author"),
                )
                attachment = attachment_copy(cv_pdf, out_dir, profile.full_name)
            except UsageLimitError as e:
                raise usage_blocked(e) from e
            except Exception as e:
                logger.bind(
                    code="email_draft_failed", params={"job": job_id, "error": type(e).__name__}
                ).warning("job {}: could not write the email: {}", job_id, type(e).__name__)
                return fail(
                    f"could not write the email ({type(e).__name__})", {"error": type(e).__name__}
                )
            draft = {
                "to": addr,
                "subject": made.subject,
                "body": made.body,
                "attachment": str(attachment),
                **({"problem": made.problem} if made.problem else {}),
            }
            if apply_cfg.live:  # the UI edits this copy; a retry or confirm reuses it
                with self.db.begin() as s:
                    row = s.get_one(Job, job_id)
                    row.data = {**row.data, "email_draft": draft}

        sender = (self.cfg.email.imap_user or profile.email).strip()
        try:
            msg = build_message(
                profile.full_name,
                sender,
                OutgoingEmail(
                    draft["to"],
                    draft["subject"],
                    draft["body"],
                    [Path(draft["attachment"])],
                    reply_to=(
                        profile.email
                        if valid_address(profile.email)
                        and profile.email.strip().lower() != sender.lower()
                        else None
                    ),
                ),
            )
        except (ValueError, OSError) as e:
            return fail(f"the email could not be built: {e}", {"error": type(e).__name__})

        if not apply_cfg.live:
            eml = str(save_eml(msg, out_dir / "application.eml"))
            note = f"dry run: email to {addr} prepared, not sent"
            if draft.get("problem"):
                note += " (the AI wrote the body in Arabic, so it is blank; a live run asks you)"
            with self.db.begin() as s:
                row = s.get_one(Job, job_id)
                _event(s, row, note, [eml], "email_preview", {"to": addr})
                row.data = {**row.data, "dry_run_at": utcnow().isoformat()}
            return Outcome("dry_run", note, [eml])

        if draft.get(
            "problem"
        ):  # only the user's edit clears it; never sent, whatever the settings
            return park(
                ActionKind.confirm_email,
                f"The AI wrote the email to {addr} in Arabic; write the message yourself",
                "confirm_email",
                {"to": addr, "subject": draft["subject"], "problem": draft["problem"]},
            )
        if not apply_cfg.submit_without_asking and not job.data.get("submit_confirmed"):
            return park(
                ActionKind.confirm_email,
                f"ready to email {addr}: check the message and confirm",
                "confirm_email",
                {"to": addr, "subject": draft["subject"]},
            )
        vault = self._unlocked_vault()
        if vault is None:
            return park(
                ActionKind.login_issue,
                "Unlock (or create) the vault so the app can sign in to your email",
                self._vault_code(),
                {"site": "your email"},
            )
        with self.db.begin() as s:
            row = s.get_one(Job, job_id)
            if row.state != JobState.applying:
                transition(s, row, JobState.applying, "sending the email", code="submitting")
        try:
            message_id = await asyncio.to_thread(send, self.cfg.email, vault, profile.email, msg)
        except NoCredentials:
            return park(
                ActionKind.login_issue,
                "Connect your email in Setup so the app can send applications",
                "needs_email",
                {"purpose": "send"},
            )
        except SmtpError as e:
            return fail(
                f"the email was not sent ({type(e).__name__}): {e}",
                {"error": type(e).__name__, "detail": str(e)},
            )
        eml = str(save_eml(msg, out_dir / "sent.eml"))
        now = utcnow().isoformat()
        with self.db.begin() as s:
            row = s.get_one(Job, job_id)
            row.data = {
                **row.data,
                "email_sent": {"to": addr, "message_id": message_id, "sent_at": now},
                "applied_at": now,
            }
            transition(
                s,
                row,
                JobState.applied,
                f"application emailed to {addr}",
                [eml],
                "applied_by_email",
                {"to": addr, "message_id": message_id},
            )
        return Outcome("applied", f"emailed {addr}", [eml])

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
        tried_google = tried_account = False

        def park(
            kind: ActionKind,
            message: str,
            code: str,
            params: dict[str, Any] | None = None,
            questions: list[dict[str, Any]] | None = None,
            answers: dict[str, Any] | None = None,
        ) -> Outcome:
            with self.db.begin() as s:
                job = s.get_one(Job, info.id)
                _park(
                    s, job, kind, message, questions or [], answers or {}, shots[-1:], code, params
                )
            return Outcome("needs_user", message, shots[-1:])

        def fail(reason: str, code: str) -> Outcome:
            with self.db.begin() as s:
                job = s.get_one(Job, info.id)
                if job.state != JobState.applying:
                    transition(s, job, JobState.applying, "filling the application", code="filling")
                transition(s, job, JobState.failed, reason, shots[-1:], code)
            return Outcome("failed", reason, shots[-1:])

        def by_hand(reason: str, code: str) -> Outcome:
            """A dead end: the user finishes it in their own browser with what was prepared."""
            return park(
                ActionKind.apply_by_hand,
                f"{BY_HAND_MSG} ({reason})",
                "apply_by_hand",
                {"why": code, "site": urlparse(page.url).netloc},
                answers=filled,
            )

        hops = 0
        for n in range(1, MAX_AGENT_PAGES + 1):
            r = await step(
                page, self.provider, ctx, self.bank, cv, summary, brief, out_dir, dry_run=not live
            )
            shots.append(str(out_dir / f"page_{n}.png"))
            await page.screenshot(path=shots[-1], full_page=True)
            filled.update(_summary(r.questions, r.answers, r.sources))
            if await captcha_shown(page):
                return park(ActionKind.captcha, CAPTCHA_MSG, "captcha")
            if r.page_kind in ("login", "signup"):
                # sign-up is never touched in a dry run; one try, so a site that keeps asking parks
                if live and apply_cfg.google_signin and not tried_google:
                    tried_google = True
                    google = await sign_in_with_google(page, profile.email)
                    if google == "signed_in":
                        with self.db.begin() as s:
                            job = s.get_one(Job, info.id)
                            _event(s, job, "signed in with Google", [], "signed_in_google")
                        await page.goto(
                            info.apply_url or info.url,
                            wait_until="domcontentloaded",
                            timeout=60000,
                        )
                        await _settle(page)
                        continue
                    if google == "needs_user":
                        return park(
                            ActionKind.login_issue,
                            f"Google needs you for this site: {hand_off('sign in with Google')}",
                            "google_needed",
                        )
                if not tried_account:  # one try: a site that keeps asking parks
                    tried_account = True
                    gated = await self._agent_account(
                        page, info, ctx, profile, out_dir, brief, park
                    )
                    if gated is not None:
                        return gated
                    await page.goto(
                        info.apply_url or info.url, wait_until="domcontentloaded", timeout=60000
                    )
                    await _settle(page)
                    continue
                return park(
                    ActionKind.login_issue,
                    f"This site needs an account: {hand_off('sign in')}",
                    "account_needed",
                )
            if r.missing:
                return park(
                    ActionKind.unknown_question,
                    f"{len(r.missing)} question(s) need your answer",
                    "unknown_question",
                    {"n": len(r.missing)},
                    [_missing_dict(m) for m in r.missing],
                )
            if r.failed or r.unfilled or r.errors:
                empty = [f"{label}: still empty" for label in r.unfilled]
                problems = [*r.failed.values(), *empty, *r.errors]
                detail = "; ".join(problems)[:500]
                return park(
                    ActionKind.validation_error,
                    detail,
                    "validation_error",
                    {"detail": detail},
                    answers=filled,
                )
            if r.action == "open":  # a job ad: press its Apply and see where it leads
                hops += 1
                if hops > MAX_APPLY_HOPS:
                    return by_hand("Apply kept leading to more job ads", "too_many_hops")
                before = await _where(page)
                await press_apply(page, r)
                await _settle(page)
                # same page, no new questions, even after waiting: e.g. a sign-up teaser popup
                if not await _moved_on(page, before):
                    return by_hand("pressing Apply opened nothing", "apply_no_effect")
                if assisted(page.url, apply_cfg.assisted_hosts):
                    return await self._park_in_browser(info.id, page.url, filled)
                handed = await self._hand_to_handler(page, info, ctx, profile, out_dir)
                if handed is not None:
                    return handed
                continue
            if r.code in ("not_eligible", "posting_gone"):
                with self.db.begin() as s:
                    transition(
                        s, s.get_one(Job, info.id), JobState.skipped, r.reason, shots[-1:], r.code
                    )
                return Outcome("skipped", r.reason, shots[-1:])
            if r.action == "stop" or r.button is None:
                return by_hand(r.reason or "no way forward", r.code or "no_way_forward")
            if r.action == "next":
                await press_next(page, r)
                await _settle(page)
                continue

            # r.action == "submit" and nothing on the page is open
            if not live:
                msg = f"{len(filled)} fields filled on {n} pages"
                with self.db.begin() as s:
                    job = s.get_one(Job, info.id)
                    _event(
                        s,
                        job,
                        f"dry run: {msg}, not submitted",
                        shots,
                        "dry_run_agent",
                        {"fields": len(filled), "pages": n},
                    )
                    job.data = {**job.data, "dry_run_at": utcnow().isoformat(), "filled": filled}
                return Outcome("dry_run", msg, shots)
            with self.db.begin() as s:
                job = s.get_one(Job, info.id)
                if not apply_cfg.submit_without_asking and not job.data.get("submit_confirmed"):
                    message = "ready to submit: check the form and confirm"
                    _park(
                        s,
                        job,
                        ActionKind.confirm_submit,
                        message,
                        [],
                        filled,
                        shots[-1:],
                        "confirm_submit",
                    )
                    return Outcome("needs_user", "waiting for your confirmation", shots[-1:])
                transition(s, job, JobState.applying, "submitting", code="submitting")
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
                    transition(
                        s, job, JobState.applied, "confirmation page seen", proof, "confirmed"
                    )
                return Outcome("applied", "submitted and confirmed", proof)
            shots.append(done)
            if await captcha_shown(page):
                return park(ActionKind.captcha, CAPTCHA_MSG, "captcha", answers=filled)
            if errors := await page_errors(page):
                detail = "; ".join(errors)[:500]
                return park(
                    ActionKind.validation_error,
                    detail,
                    "validation_error",
                    {"detail": detail},
                    answers=filled,
                )
            return fail("no confirmation page after submitting", "no_confirmation")
        return by_hand(f"more than {MAX_AGENT_PAGES} pages", "too_many_pages")

    async def _agent_account(
        self,
        page: Page,
        info: JobInfo,
        ctx: Context,
        profile: Profile,
        out_dir: Path,
        brief: dict[str, str],
        park: Callable[..., Outcome],
    ) -> Outcome | None:
        """A site without a handler wants an account: sign in with the vault's login for this
        host, or (live only) sign up first: password saved before the click, the emailed link
        or code read from the inbox. None = signed in; the caller goes back to the job."""
        host = (urlparse(page.url).hostname or "").removeprefix("www.")
        vault = self._unlocked_vault()
        account = find_account(vault, WEB, host) if vault is not None else None
        if account is None and not self.cfg.apply.live:  # a dry run never touches sign-up
            msg = f"would sign up on {host}"
            with self.db.begin() as s:
                job = s.get_one(Job, info.id)
                _event(
                    s, job, f"dry run: {msg}, not submitted", [], "dry_run_signup", {"site": host}
                )
                job.data = {**job.data, "dry_run_at": utcnow().isoformat()}
            return Outcome("dry_run", msg)
        if vault is None:
            msg = f"Unlock (or create) the vault so the app can sign in to {host}"
            return park(ActionKind.login_issue, msg, self._vault_code(), {"site": host})
        if account is None:
            try:
                mail = await asyncio.to_thread(credentials, self.cfg.email, vault, profile.email)
            except EmailLoginError as e:
                return park(
                    ActionKind.login_issue, str(e), "email_login_failed", {"detail": str(e)}
                )
            if mail is None:
                msg = "Connect your email in Setup so the app can read the verification email"
                return park(
                    ActionKind.login_issue, msg, "needs_email", {"site": host, "purpose": "verify"}
                )
            if await signup_link_needed(page) and not await open_signup(page):
                msg = f"No sign-up link found on {host}: {hand_off('create an account')}"
                return park(ActionKind.login_issue, msg, "account_needed")
            # saved before the sign-up click: a crash never loses the password
            account = create_account(vault, WEB, host, profile.email, PasswordRules())
            since = utcnow()
            r = await step(
                page, self.provider, ctx, self.bank, cv_text(profile), profile_summary(ctx),
                brief, out_dir, dry_run=False, password=account.password,
            )  # fmt: skip
            if r.missing:
                return park(
                    ActionKind.unknown_question,
                    f"{len(r.missing)} question(s) need your answer",
                    "unknown_question",
                    {"n": len(r.missing)},
                    [_missing_dict(m) for m in r.missing],
                )
            if not r.ready or r.button is None:
                detail = "; ".join([*r.failed.values(), *r.unfilled, *r.errors]) or r.reason
                msg = f"Sign-up on {host} needs you ({detail[:300]}): {hand_off('create it')}"
                return park(ActionKind.login_issue, msg, "signup_failed", {"site": host})
            await (await locate(page, r.button.id)).click()
            await _settle(page)
            if await captcha_shown(page):
                return park(ActionKind.captcha, CAPTCHA_MSG, "captcha")
            if await login_form(page) or VERIFY_PAGE.search(await page_text(page, 5000)):
                try:
                    found = await wait_for_verification(
                        self.cfg.email, *mail, [host], since, self.provider
                    )
                except EmailLoginError as e:
                    return park(
                        ActionKind.login_issue, str(e), "email_login_failed", {"detail": str(e)}
                    )
                if found is not None and found.link:
                    await page.goto(found.link, wait_until="domcontentloaded", timeout=60000)
                    await _settle(page)
                elif found is None or not found.code or not await enter_code(page, found.code):
                    msg = f"No verification email from {host} arrived in time: check your inbox"
                    return park(ActionKind.login_issue, msg, "verification_missing", {"site": host})
            account = mark_active(vault, account, WEB, host)
            with self.db.begin() as s:
                job = s.get_one(Job, info.id)
                _event(s, job, f"account created on {host}", [], "account_created", {"site": host})
        # ponytail: an emailed sign-in code after the password is not read; it parks below
        if await login_form(page):
            await sign_in(page, account.username, account.password)
            await _settle(page)
            if await login_form(page):
                msg = f"{host} rejected the saved login: {hand_off('sign in')}"
                return park(ActionKind.login_issue, msg, "login_rejected", {"site": host})
        if account.status != "active":
            mark_active(vault, account, WEB, host)
        return None

    async def _hand_to_handler(
        self, page: Page, info: JobInfo, ctx: Context, profile: Profile, out_dir: Path
    ) -> Outcome | None:
        """Apply led to an ATS we have a handler for (Greenhouse, Lever, Ashby): remember the
        real link on the job and let the handler fill it. None = keep going with the agent."""
        found = detect(page.url)
        if found is None:
            return None
        with self.db.begin() as s:
            job = s.get_one(Job, info.id)
            job.ats = found[0]
            job.data = {**job.data, "apply_url": page.url}
            _event(s, job, f"Apply leads to {found[0]}", [], "apply_resolved", {"ats": found[0]})
            handler, real = HANDLERS.get(found[0]), job_info(job)
        if handler is None or real is None:
            return None
        return await self._fill_and_decide(page, handler, real, ctx, profile, out_dir)

    async def _form_again(self, page: Page) -> bool:
        """Extra check once the confirmation text matched: if the page still has form controls,
        ask the model whether it really is a form. Model unavailable = trust the text."""
        try:
            controls = await snapshot(page)
            if not controls:
                return False
            remember_bank_secrets(self.db)
            fmap = await field_map(
                self.provider, controls, await page.title(), await page_text(page, 2000)
            )
        except Exception:
            return False
        return fmap.page_kind in ("form", "review", "login", "signup")

    def _unlocked_vault(self) -> Vault | None:
        vault = self._vault if self._vault is not None else vault_for(self.settings, self.db)
        if not vault.unlocked() and vault.initialized():
            vault.unlock_from_keyring()
        return vault if vault.unlocked() else None

    def _vault_code(self) -> str:
        """Park code for a missing vault: `needs_vault` (never created) or `vault_locked`."""
        vault = self._vault if self._vault is not None else vault_for(self.settings, self.db)
        return "vault_locked" if vault.initialized() else "needs_vault"

    async def _account_gate(
        self, page: Page, handler: Handler, info: JobInfo, profile: Profile, out_dir: Path
    ) -> Outcome | None:
        """Sign in (signing up first when live) if the ATS needs an account. None = signed in."""
        tenant = handler.account_tenant(info)
        if tenant is None or await handler.signed_in(page):
            return None
        site = f"{handler.ats} ({tenant})"
        live = self.cfg.apply.live

        async def park(
            kind: ActionKind, message: str, code: str, params: dict[str, Any] | None = None
        ) -> Outcome:
            shot = str(out_dir / "account.png")
            await page.screenshot(path=shot)
            with self.db.begin() as s:
                _park(s, s.get_one(Job, info.id), kind, message, [], {}, [shot], code, params)
            return Outcome("needs_user", message, [shot])

        vault = self._unlocked_vault()
        if vault is None:
            msg = f"Unlock (or create) the vault so the app can sign in to {site}"
            return await park(ActionKind.login_issue, msg, self._vault_code(), {"site": site})
        account = find_account(vault, handler.ats, tenant)
        if account is None:
            if not live:  # no typing, no clicks: sign-up forms are never touched in a dry run
                msg = f"would create an account on {site}"
                with self.db.begin() as s:
                    job = s.get_one(Job, info.id)
                    _event(
                        s,
                        job,
                        f"dry run: {msg}, not submitted",
                        [],
                        "dry_run_signup",
                        {"site": site},
                    )
                    job.data = {**job.data, "dry_run_at": utcnow().isoformat()}
                return Outcome("dry_run", msg)
            try:
                mail = await asyncio.to_thread(credentials, self.cfg.email, vault, profile.email)
            except EmailLoginError as e:  # e.g. the Microsoft sign-in expired
                return await park(
                    ActionKind.login_issue, str(e), "email_login_failed", {"detail": str(e)}
                )
            if mail is None:
                msg = "Connect your email in Setup so the app can read the verification email"
                return await park(
                    ActionKind.login_issue, msg, "needs_email", {"site": site, "purpose": "verify"}
                )
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
                    return await park(
                        ActionKind.login_issue, str(e), "email_login_failed", {"detail": str(e)}
                    )
                if found is None or not (found.link or found.code):
                    msg = f"No verification email from {site} arrived in time: check your inbox"
                    return await park(
                        ActionKind.login_issue, msg, "verification_missing", {"site": site}
                    )
                if found.link:
                    await handler.follow_link(page, found.link)
                elif found.code:
                    await handler.enter_code(page, found.code)
            account = mark_active(vault, account, handler.ats, tenant)
        if not await handler.signed_in(page):
            await handler.login(page, info, account)
            if await handler.two_factor_shown(page):
                msg = f"{site} wants a sign-in code: {hand_off('enter the code')}"
                return await park(ActionKind.two_factor, msg, "two_factor", {"site": site})
            if not await handler.signed_in(page):
                msg = f"{site} rejected the saved login: {hand_off('sign in')}"
                return await park(ActionKind.login_issue, msg, "login_rejected", {"site": site})
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
                    "unknown_question",
                    {"n": len(r.missing)},
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
                    "validation_error",
                    {"detail": "; ".join(failed)[:500]},
                )
            return Outcome("needs_user", "some fields could not be filled", [shot])

        with self.db.begin() as s:
            job = s.get_one(Job, info.id)
            if not apply_cfg.live:
                _event(
                    s,
                    job,
                    f"dry run: {len(filled)} fields filled, not submitted",
                    [shot],
                    "dry_run_filled",
                    {"fields": len(filled)},
                )
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
                    "confirm_submit",
                )
                return Outcome("needs_user", "waiting for your confirmation", [shot])
            transition(s, job, JobState.applying, "submitting", code="submitting")

        await click_submit(page, handler, dry_run=not apply_cfg.live)
        done = str(out_dir / "after_submit.png")
        confirmed = await handler.confirmed(page)
        await page.screenshot(path=done, full_page=True)
        with self.db.begin() as s:
            job = s.get_one(Job, info.id)
            if confirmed:
                job.data = {**job.data, "applied_at": utcnow().isoformat(), "filled": filled}
                transition(
                    s, job, JobState.applied, "confirmation page seen", [shot, done], "confirmed"
                )
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
                    "captcha",
                )
                return Outcome("needs_user", "captcha", [done])
            if errors := await handler.errors(page):
                detail = "; ".join(errors)[:500]
                _park(
                    s,
                    job,
                    ActionKind.validation_error,
                    detail,
                    [],
                    filled,
                    [done],
                    "validation_error",
                    {"detail": detail},
                )
                return Outcome("needs_user", "the form rejected some answers", [done])
            transition(
                s,
                job,
                JobState.failed,
                "no confirmation page after submitting",
                [shot, done],
                "no_confirmation",
            )
            return Outcome("failed", "no confirmation seen", [shot, done])


_END_STATE = {"needs_user": JobState.needs_user, "failed": JobState.failed,
              "skipped": JobState.skipped}  # fmt: skip


def _outcome_params(db: sessionmaker[Session], job_id: int, outcome: Outcome) -> dict[str, Any]:
    """`apply_job` params: job, status and, for needs_user/failed/skipped, a stable `reason` code
    (the job's last event if it ended in that state) plus `questions` for a parked job."""
    params: dict[str, Any] = {"job": job_id, "status": outcome.status}
    end = _END_STATE.get(outcome.status)
    if end is None:
        return params
    with db() as s:
        last = s.scalars(
            select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id.desc()).limit(1)
        ).first()
        params["reason"] = (
            outcome.reason or (last.code if last and last.to_state == end else None) or "unknown"
        )
        if end == JobState.needs_user:
            item = s.scalars(
                select(ActionItem).where(ActionItem.job_id == job_id).order_by(ActionItem.id.desc())
            ).first()
            params["questions"] = len(item.questions) if item else 0
    return params


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
        logger.bind(
            code="apply_start",
            params={"jobs": sum(map(len, sites.values())), "sites": len(sites),
                    "parallel": parallel, "live": live},
        ).info(
            "apply: {} jobs on {} sites, {} at a time ({}) [{}]",
            sum(map(len, sites.values())),
            len(sites),
            parallel,
            "live" if live else "dry run",
            ", ".join(f"{site}: {len(ids)}" for site, ids in sites.items()),
        )  # fmt: skip
        running = asyncio.Semaphore(parallel)

        async def work(ids: list[int]) -> None:
            async with running:
                for n, job_id in enumerate(ids):
                    if n:  # pace between two applications on the same site
                        await asyncio.sleep(random.uniform(lo, max(lo, hi)))  # noqa: S311
                    with db() as s:
                        row = s.get_one(Job, job_id)
                        title, company = row.title, row.company
                    logger.bind(
                        code="apply_job_start",
                        params={"job": job_id, "title": title, "company": company},
                    ).info("job {}: starting ({} at {})", job_id, title, company)
                    outcome = await applier.apply(job_id)
                    counts[outcome.status] += 1  # no await in between: no race
                    logger.bind(code="apply_job", params=_outcome_params(db, job_id, outcome)).info(
                        "job {}: {} ({})", job_id, outcome.status, outcome.message
                    )

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
