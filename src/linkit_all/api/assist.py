"""LinkIt Fill: the browser extension that fills an application in the user's own browser.

Used for ban-risk sites (LinkedIn Easy Apply, Indeed Apply) and for any job the app handed to
the user. The extension sends the page's controls; each is identified by its label or field
name and answered from the app's data, and the AI is asked only for what is not recorded (the
same answer engine as the app's agent; sensitive questions never reach the AI). The extension
fills them. It never presses Next or Submit: the user does (CLAUDE.md §5.5).

Every call needs the pairing token shown in Settings > Applying; the extension keeps it. The
server only listens on 127.0.0.1, and data goes only to the provider the user chose.
"""

import hmac
import re
import secrets
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.agent import Control, page_questions
from linkit_all.apply.answers import is_cover_letter, sensitive_category
from linkit_all.apply.assist import (
    AnswerBank,
    answer_questions,
    keepable,
    profile_summary,
    role_key,
    scope_of,
)
from linkit_all.apply.handlers.base import GENERIC_CONFIRMATION
from linkit_all.apply.runner import job_context
from linkit_all.core.config import Settings
from linkit_all.core.models import (
    ActionItem,
    ActionKind,
    ActionStatus,
    Job,
    JobState,
    Profile,
    utcnow,
)
from linkit_all.core.search import SearchConfig, load_search
from linkit_all.core.state import transition
from linkit_all.matching.rank import cv_text
from linkit_all.providers.base import LLMProvider
from linkit_all.sources.text import norm, norm_company

router = APIRouter(prefix="/api/assist")
KINDS = (ActionKind.apply_in_browser, ActionKind.apply_by_hand)


def _db(request: Request) -> sessionmaker[Session]:
    db: sessionmaker[Session] = request.app.state.db
    return db


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def token_path(settings: Settings) -> Path:
    return settings.data_dir / "assist_token"


def pairing_token(settings: Settings) -> str:
    """The extension's pairing token, made on first use and kept in the data folder."""
    path = token_path(settings)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(24), "utf-8")
    return path.read_text("utf-8").strip()


def _check(request: Request, token: str | None) -> None:
    if not token or not hmac.compare_digest(token, pairing_token(_settings(request))):
        raise HTTPException(
            401, "Pair the LinkIt extension: copy the code from Settings > Applying"
        )


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").removeprefix("www.")


def _open_items(s: Session) -> list[tuple[ActionItem, Job]]:
    rows = s.execute(
        select(ActionItem, Job)
        .join(Job, Job.id == ActionItem.job_id)
        .where(ActionItem.status == ActionStatus.open, ActionItem.kind.in_(KINDS))
        .order_by(ActionItem.id.desc())
    ).all()
    return [(item, job) for item, job in rows]


@router.get("/token")
def get_token(request: Request) -> dict[str, str]:
    """For the app's own Settings page (same-origin: a GET from another site cannot read it)."""
    if request.headers.get("sec-fetch-site") not in (None, "same-origin"):
        raise HTTPException(403, "only the app itself can read the pairing code")
    folder = Path(__file__).parent.parent / "extension"
    return {"token": pairing_token(_settings(request)), "extension_dir": str(folder)}


@router.get("/hosts")
def hosts(request: Request, x_linkit_token: str | None = Header(None)) -> dict[str, list[str]]:
    """Sites with a job waiting for the user: the extension shows its panel only there."""
    _check(request, x_linkit_token)
    with _db(request)() as s:
        found = {_host(u) for _, job in _open_items(s) for u in _urls(job)}
    return {"hosts": sorted(h for h in found if h)}


_SITE_JOB_ID = (
    re.compile(r"/jobs/view/(?:[^/?#]*-)?(\d{6,})"),  # LinkedIn
    re.compile(
        r"[?&](?:currentJobId|jl|jobListingId|jk|vjk)=([\w-]+)"
    ),  # LinkedIn lists, Glassdoor, Indeed
)


def _urls(job: Job) -> set[str]:
    return {u for u in (job.url, job.data.get("apply_url")) if u}


def _site_job_id(url: str) -> str:
    return next((m[1].lower() for rx in _SITE_JOB_ID if (m := rx.search(url))), "")


def _path(url: str) -> str:
    return f"{_host(url)}{urlparse(url).path.rstrip('/')}".lower()


def _same_page(job_path: str, here: str) -> bool:
    return "/" in job_path and (here == job_path or here.startswith(job_path + "/"))


class PageIn(BaseModel):
    url: str = Field(max_length=4000)
    title: str = Field("", max_length=500)
    heading: str = Field("", max_length=2000)
    text: str = Field("", max_length=20000)


def _named_on_page(job: Job, page: PageIn) -> bool:
    role, company = role_key(job.title), norm_company(job.company)
    return (
        bool(role and company)
        and company != norm_company("Unknown")
        and f" {role} " in f" {role_key(f'{page.title} {page.heading}')} "
        and f" {company} " in f" {norm(f'{page.title} {page.heading} {page.text}')} "
    )


def _job_on_page(jobs: list[Job], page: PageIn) -> Job | None:
    """The waiting job this page is about, or None: never a guess. The site's own job id decides
    when the address has one (several Glassdoor jobs share a path and differ only in `jl`); then
    the address; then the job's title and company both named on the page."""
    if key := _site_job_id(page.url):
        return next((j for j in jobs if key in {_site_job_id(u) for u in _urls(j)}), None)
    here = _path(page.url)
    for hits in (
        [j for j in jobs if any(_same_page(_path(u), here) for u in _urls(j))],
        [j for j in jobs if _named_on_page(j, page)],
    ):
        if hits:
            return hits[0] if len(hits) == 1 else None
    return None


@router.post("/match")
def match(
    request: Request, body: PageIn, x_linkit_token: str | None = Header(None)
) -> dict[str, Any]:
    """The waiting job for the page the user is on. 404 = none of them."""
    _check(request, x_linkit_token)
    with _db(request)() as s:
        job = _job_on_page([j for _, j in _open_items(s)], body)
        if job is None:
            raise HTTPException(404, "no job waiting on this page")
        hosts = sorted(h for h in {_host(u) for u in _urls(job)} if h)
        return {"job_id": job.id, "title": job.title, "company": job.company, "hosts": hosts}


class ControlIn(BaseModel):
    id: str = Field(max_length=40)
    kind: str = Field(max_length=20)
    name: str = Field("", max_length=300)
    required: bool = False
    options: list[str] = Field(default_factory=list, max_length=2000)
    value: str = Field("", max_length=200)
    empty: bool = True
    html_name: str = Field("", max_length=200)
    type: str = Field("", max_length=20)
    href: str = Field("", max_length=2000)


class PlanIn(BaseModel):
    job_id: int | None = None  # None: a page that is not one of the waiting jobs
    fill_all: bool = False  # the user asked: the AI may answer optional fields too
    title: str = Field("", max_length=300)
    text: str = Field("", max_length=4000)
    controls: list[ControlIn] = Field(max_length=400)


def _page_job(body: PlanIn) -> Job:
    """Stands in for a job on a page that is none of the waiting ones (never saved). No title
    and no company, so an answer tied to a role or company is not kept for later."""
    return Job(
        source="page", url="", title="", company="Unknown", location="",
        description=f"{body.title}\n{body.text}", dedupe_hash="", data={},
    )  # fmt: skip


@router.post("/plan")
async def plan(
    request: Request, body: PlanIn, x_linkit_token: str | None = Header(None)
) -> dict[str, Any]:
    """What to type into this step of the form: {control id: value}, plus what only the user
    can answer. App data first; the AI only for answers not recorded. Nothing is clicked."""
    _check(request, x_linkit_token)
    from linkit_all.pipeline import _get_embedder, ai_settings
    from linkit_all.providers import ProviderError, UsageLimitError, get_provider

    db, settings = _db(request), _settings(request)
    with db() as s:
        job = _page_job(body) if body.job_id is None else s.get(Job, body.job_id)
        profile = s.get(Profile, 1)
        if job is None or profile is None:
            raise HTTPException(404, "unknown job")
        s.expunge_all()
    cfg = load_search(db) or SearchConfig()
    provider: LLMProvider | None
    try:
        provider = get_provider(ai_settings(settings, cfg), cache=db)
    except ProviderError:  # no AI set up: recorded answers still fill the form
        provider = None
    questions = page_questions([Control(**c.model_dump()) for c in body.controls])
    ctx = job_context(profile, job, str(job.data.get("cv_pdf") or profile.cv_path or ""))
    out_dir = settings.data_dir / "applications" / f"job_{job.id or 'page'}"
    out_dir.mkdir(parents=True, exist_ok=True)
    brief = {"title": job.title, "company": job.company, "description": job.description}
    bank = AnswerBank(db, await _get_embedder(settings))
    args = (cv_text(profile), profile_summary(ctx), brief, out_dir)
    try:
        r = await answer_questions(questions, ctx, bank, provider, *args, ai_optional=body.fill_all)
    except UsageLimitError:  # out of AI for now: the recorded answers still count
        r = await answer_questions(questions, ctx, bank, None, *args, ai_optional=body.fill_all)
    kinds = {q.key: q.kind for q in questions}
    fill = {k: ("cv" if kinds.get(k) == "file" else v) for k, v in r.answers.items()}
    return {
        "fill": fill,
        "sources": r.sources,
        "missing": [{"id": m.question.key, "label": m.question.label} for m in r.missing],
        # what the user types here is kept: no answer yet, or one from the bank or the AI
        "asked": [q.key for q in questions if r.sources.get(q.key) in (None, "ai", "bank")],
    }


class TypedIn(BaseModel):
    job_id: int | None = None
    control: ControlIn
    value: Annotated[str, Field(max_length=20000)] | list[Annotated[str, Field(max_length=500)]]


_NOT_KEPT_KINDS = ("file", "checkbox", "date")  # a tick may be an agreement; a date goes stale
_SECRET_FIELD = re.compile(
    r"pass(word|code|phrase)|verif\w* code|one.?time|\botp\b|captcha|security (code|answer)|"
    r"\bcv[vc]\b|card (number|no)|\biban\b|account (number|no)|\bssn\b|social security|"
    r"(national|government|tax) id|id (number|no)\b|passport|"
    r"كلمة (ال)?(سر|مرور)|رمز التحقق|الرقم القومي|جواز",
    re.IGNORECASE,
)


@router.post("/typed")
def typed(
    request: Request, body: TypedIn, x_linkit_token: str | None = Header(None)
) -> dict[str, Any]:
    """The user filled or corrected a field in their browser: kept as their own answer. Nothing
    they typed without meaning to record it may later answer for them on a legal or sensitive
    question (CLAUDE.md §2), so those, and secrets, are not kept."""
    _check(request, x_linkit_token)
    db = _db(request)
    found = page_questions([Control(**{**body.control.model_dump(), "empty": True})])
    q = found[0] if found else None
    if (
        q is None
        or not body.value
        or q.kind in _NOT_KEPT_KINDS
        or _SECRET_FIELD.search(f"{q.label} {q.name}")
        or is_cover_letter(q)
        or sensitive_category(q)
    ):
        return {"saved": False}
    with db.begin() as s:
        job = s.get(Job, body.job_id) if body.job_id is not None else None
        if job is None and body.job_id is not None:
            raise HTTPException(404, "unknown job")
        where = scope_of(q.label, job.title if job else "", job.company if job else "Unknown")
        if not keepable(where):
            return {"saved": False}
        AnswerBank(db).save(q.label, body.value, "user", session=s, scope=where)
    return {"saved": True, "scope": where.kind}


@router.get("/cv/{job_id}")
def cv_file(request: Request, job_id: int, x_linkit_token: str | None = Header(None)) -> Any:
    """The CV this application sends (tailored if it was, else the user's own; job 0 is a page
    that is none of the waiting jobs), for the form's upload box."""
    _check(request, x_linkit_token)
    with _db(request)() as s:
        job, profile = s.get(Job, job_id), s.get(Profile, 1)
        found = (job.data.get("cv_pdf") if job else "") or (profile.cv_path if profile else "")
    path = Path(str(found or ""))
    if not found or not path.is_file():
        raise HTTPException(404, "no CV file for this job yet")
    return FileResponse(path, filename=path.name)


class DoneIn(BaseModel):
    job_id: int
    text: str = Field("", max_length=20000)  # the page text, kept as proof when it confirms


@router.post("/done")
def done(
    request: Request, body: DoneIn, x_linkit_token: str | None = Header(None)
) -> dict[str, Any]:
    """The user submitted it in their browser: the job is applied (by hand) and its Needs-you
    card closes. `confirmed` says whether the page showed a confirmation."""
    _check(request, x_linkit_token)
    confirmed = bool(GENERIC_CONFIRMATION.search(body.text.lower()))
    with _db(request).begin() as s:
        job = s.get(Job, body.job_id)
        if job is None:
            raise HTTPException(404, "unknown job")
        if job.state != JobState.applied:
            if job.state != JobState.applying:
                transition(
                    s, job, JobState.applying, "you applied in your browser", code="applied_by_hand"
                )
            transition(
                s, job, JobState.applied, "you applied in your browser", code="applied_by_hand",
                params={"confirmed": confirmed},
            )  # fmt: skip
        for item in s.scalars(
            select(ActionItem).where(
                ActionItem.job_id == job.id, ActionItem.status == ActionStatus.open
            )
        ):
            item.status, item.resolved_at = ActionStatus.resolved, utcnow()
    return {"ok": True, "confirmed": confirmed}
