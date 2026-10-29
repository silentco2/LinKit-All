"""REST API for the local UI. Everything lives under /api."""

import asyncio
import hashlib
import json
import re
import shutil
import sys
from dataclasses import asdict
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, ValidationError, field_validator
from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.api.events import EventBus
from linkit_all.api.runner import PipelineRunner, RunBusy
from linkit_all.apply.answers import ApplicationAnswers, Question, sensitive_category
from linkit_all.apply.assist import AnswerBank
from linkit_all.apply.browser import UserBrowser, fresh_live_shot, profile_dir
from linkit_all.apply.email_send import (
    NoCredentials,
    OutgoingEmail,
    SmtpError,
    build_message,
    send,
)
from linkit_all.apply.email_verify import EmailLoginError, check_login, credentials
from linkit_all.apply.runner import is_pickable
from linkit_all.apply.vault import Vault, VaultError, VaultLocked, WrongPassphrase
from linkit_all.core.api_keys import KNOWN, delete_keys, get_keys, set_keys
from linkit_all.core.config import Settings
from linkit_all.core.infer import InferredValue, infer, read_cv
from linkit_all.core.models import (
    ActionItem,
    ActionKind,
    ActionStatus,
    AnswerEntry,
    Job,
    JobEvent,
    JobState,
    Profile,
    Run,
    SearchConfigRow,
    TailoredCV,
    Tier,
    utcnow,
)  # fmt: skip
from linkit_all.core.presets import (
    PACE,
    PICKINESS,
    Track,
    country_preset,
    pace_of,
    pickiness_of,
    source_preset,
)
from linkit_all.core.profile import (
    ProfileFields,
    approve_cv,
    cv_state,
    load_fields,
    save_cv,
    save_fields,
)
from linkit_all.core.scheduler import apply_schedule, next_runs
from linkit_all.core.search import (
    DEFAULT_TELEGRAM_CHANNELS,
    WORK_MODES,
    SearchConfig,
    SourcesSection,
    load_search,
    save_search,
)
from linkit_all.core.state import InvalidTransition, can_transition, transition
from linkit_all.core.tools import soffice_path, tectonic_path
from linkit_all.matching.reasons import FilterEvent, job_reason
from linkit_all.pipeline import STAGES, PipelineError, ai_settings
from linkit_all.reports import build_report, export_csv, export_pdf
from linkit_all.sources import registry
from linkit_all.sources.base import OPT_IN_KINDS, Source
from linkit_all.sources.text import norm_company

router = APIRouter(prefix="/api")
GHOST_FILTERABLE = (
    JobState.discovered, JobState.enriched, JobState.ranked, JobState.scored,
    JobState.below_threshold, JobState.awaiting_review, JobState.queued_apply,
)  # fmt: skip


def _db(request: Request) -> sessionmaker[Session]:
    db: sessionmaker[Session] = request.app.state.db
    return db


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _runner(request: Request) -> PipelineRunner:
    runner: PipelineRunner = request.app.state.runner
    return runner


def _vault(request: Request) -> Vault:
    vault: Vault = request.app.state.vault
    return vault


def _user_browser(request: Request) -> UserBrowser:
    browser: UserBrowser = request.app.state.user_browser
    return browser


def _data_file(
    request: Request,
    path: Path,
    media_type: str = "image/png",
    headers: dict[str, str] | None = None,
) -> FileResponse:
    """Serve a file, but only one the app wrote into its own data dir."""
    path = path.resolve()
    if not path.is_relative_to(_settings(request).data_dir.resolve()) or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type=media_type, headers=headers)


# --- status -------------------------------------------------------------------


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    db = _db(request)
    fields, cv = load_fields(db)
    cfg = load_search(db)
    vault = _vault(request)
    with db() as s:
        states = dict(s.execute(select(Job.state, func.count()).group_by(Job.state)).all())
        practiced = s.scalar(
            select(func.count()).where(Job.data["dry_run_at"].as_string().is_not(None))
        )
        queue = s.scalars(
            select(Job).where(Job.state.in_([JobState.queued_apply, JobState.tailored]))
        )
        apply_cfg = (cfg or SearchConfig()).apply
        ready = sum(is_pickable(j, apply_cfg.generic_agent, apply_cfg.live) for j in queue)
    profile_ready = bool(fields.full_name and fields.email)
    cv_ready = bool(cv) and cv_state(db)[1]  # a converted PDF counts once approved
    search_ready = cfg is not None and bool(cfg.search.queries or cfg.sources.companies)
    ai_ready = cfg is not None and cfg.ai.provider is not None
    setup = {
        "cv": cv_ready,
        "ai": ai_ready,
        "profile": profile_ready,
        "roles": search_ready,
        "where": cfg is not None and any(loc.strip() for loc in cfg.search.locations),
    }
    return {
        "profile_ready": profile_ready,
        "cv_ready": cv_ready,
        "search_ready": search_ready,
        "ai_ready": ai_ready,
        "setup": {
            **setup,
            "required_done": all(setup.values()),
            "next_step": next((k for k, done in setup.items() if not done), None),
        },
        "libreoffice": soffice_path() is not None,
        "vault": {"initialized": vault.initialized(), "unlocked": vault.unlocked()},
        "states": {str(k): v for k, v in states.items()},
        "actions_open": _open_actions(db),
        "apply_live": bool(cfg and cfg.apply.live),
        "ready_to_apply": ready,
        "practiced": practiced or 0,
        "run": _runner(request).state.as_dict(),
        "app_browser": {
            "open": _user_browser(request).is_open,
            "item_id": _user_browser(request).item_id,
        },
        "live_shot": (p.stat().st_mtime if (p := fresh_live_shot(_settings(request))) else None),
        "next_run": next((t.isoformat() for t in next_runs(request.app.state.scheduler, 1)), None),
    }


def _open_actions(db: sessionmaker[Session]) -> int:
    with db() as s:
        return s.scalar(select(func.count()).where(ActionItem.status == ActionStatus.open)) or 0


# --- profile ------------------------------------------------------------------


def _segments(cv: str) -> list[dict[str, Any]]:
    from linkit_all.tailor.pipeline import cv_segments

    return [{"id": s.id, "text": s.text} for s in cv_segments(Path(cv))]


def _renderer_ok(fmt: str) -> bool:
    """Whether the program that renders this CV exists (Tectonic for .tex, else LibreOffice)."""
    return (tectonic_path() if fmt == "tex" else soffice_path()) is not None


@router.get("/profile")
def get_profile(request: Request) -> dict[str, Any]:
    fields, cv = load_fields(_db(request))
    fmt, approved = cv_state(_db(request))
    return {
        **fields.model_dump(),
        "cv_name": cv.replace("\\", "/").rsplit("/", 1)[-1] if cv else None,
        "cv_source_format": fmt,
        "cv_approved": approved,
        "cv_renderer_ok": _renderer_ok(fmt),
    }


@router.put("/profile")
def put_profile(request: Request, fields: ProfileFields) -> dict[str, Any]:
    save_fields(_db(request), fields)
    return get_profile(request)


@router.post("/profile/cv")
async def upload_cv(request: Request, filename: str) -> dict[str, Any]:
    """Raw DOCX/ODT/PDF/TEX bytes in the body (no multipart dependency needed)."""
    body = await request.body()
    try:
        cv = await asyncio.to_thread(
            save_cv, _db(request), _settings(request).data_dir, filename, body
        )
        segments = await asyncio.to_thread(_segments, str(cv))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    fmt, approved = cv_state(_db(request))
    return {
        "cv_name": cv.name,
        "segments": segments,
        "cv_source_format": fmt,
        "cv_approved": approved,
        "cv_renderer_ok": _renderer_ok(fmt),
    }


@router.post("/profile/cv/approve")
def approve_cv_route(request: Request) -> dict[str, Any]:
    """The user checked the converted PDF base; tailoring may now use it."""
    if not approve_cv(_db(request)):
        raise HTTPException(404, "No CV uploaded yet")
    return get_profile(request)


@router.get("/profile/cv/segments")
def cv_segments(request: Request) -> list[dict[str, Any]]:
    _, cv = load_fields(_db(request))
    if not cv:
        raise HTTPException(404, "No CV uploaded yet")
    return _segments(cv)


@router.get("/profile/cv/pdf")
async def cv_pdf(request: Request) -> FileResponse:

    from linkit_all.tailor.pipeline import ensure_base_pdf
    from linkit_all.tailor.render.libreoffice import RenderError

    _, cv = load_fields(_db(request))
    if not cv:
        raise HTTPException(404, "No CV uploaded yet")
    try:
        pdf = await asyncio.to_thread(ensure_base_pdf, Path(cv))
    except RenderError as e:
        raise HTTPException(503, str(e)) from e
    return FileResponse(pdf, media_type="application/pdf")


# --- search config and AI ----------------------------------------------------------


@router.get("/search")
def get_search(request: Request) -> SearchConfig:
    return load_search(_db(request)) or SearchConfig()


@router.put("/search")
def put_search(request: Request, cfg: SearchConfig) -> SearchConfig:
    save_search(_db(request), cfg)
    apply_schedule(request.app.state.scheduler, cfg)
    return cfg


@router.get("/presets")
def get_presets(request: Request) -> dict[str, Any]:
    """Pace and Pickiness presets, the field defaults, and which preset the saved config matches."""
    cfg = load_search(_db(request)) or SearchConfig()
    return {
        "pace": PACE,
        "pickiness": PICKINESS,
        "defaults": SearchConfig().model_dump(mode="json"),
        "current": {"pace": pace_of(cfg.apply), "pickiness": pickiness_of(cfg.matching)},
    }


DRY_RUN_FORM_CODES = ("dry_run_filled", "dry_run_agent")  # runner.py: a filled form + screenshots


@router.get("/golive")
def go_live(request: Request) -> dict[str, Any]:
    """Data for the "Ready to apply for real?" card. Read-only: PUT /search turns Live on."""
    db = _db(request)
    cfg = load_search(db) or SearchConfig()
    _, cv = load_fields(db)
    with db() as s:
        newest_first = s.execute(
            select(JobEvent, Job)
            .join(Job, Job.id == JobEvent.job_id)
            .where(JobEvent.code.in_(DRY_RUN_FORM_CODES))
            .order_by(JobEvent.id.desc())
            .limit(50)
        )
        picked: dict[int, tuple[JobEvent, Job]] = {}
        for event, job in newest_first:
            if event.artifacts and job.id not in picked and len(picked) < 3:
                picked[job.id] = (event, job)
        tailored = set(s.scalars(select(TailoredCV.job_id).where(TailoredCV.job_id.in_(picked))))
        samples = [
            {
                "job_id": job.id,
                "title": job.title,
                "company": job.company,
                "screenshots": [
                    f"/api/jobs/{job.id}/events/{event.id}/screenshot/{n}"
                    for n in range(len(event.artifacts))
                ],
                "tailored": job.id in tailored,
            }
            for event, job in picked.values()
        ]
        profile = s.get(Profile, 1)
        answers = ApplicationAnswers.model_validate(profile.answers if profile else {})
    return {
        "eligible": bool(samples),
        "live": cfg.apply.live,
        "samples": samples,
        "checklist": {
            "cv_approved": bool(cv) and cv_state(db)[1],
            "answers_reviewed": answers != ApplicationAnswers(),
            "caps_set": cfg.apply.daily_cap_per_site <= 40,
            "confirm_each": not cfg.apply.submit_without_asking,
        },
    }


@router.get("/schedule")
def get_schedule(request: Request) -> dict[str, Any]:
    cfg = load_search(_db(request)) or SearchConfig()
    runs = next_runs(request.app.state.scheduler) if cfg.schedule.enabled else []
    return {"enabled": cfg.schedule.enabled, "next_runs": [t.isoformat() for t in runs]}


@router.get("/ai")
def get_ai(request: Request) -> dict[str, Any]:
    cfg = load_search(_db(request)) or SearchConfig()
    try:
        effective = ai_settings(_settings(request), cfg)
    except PipelineError:
        effective = _settings(request)
    return {
        "provider": effective.provider,
        "model": effective.model,
        "available": {
            "codex_cli": shutil.which("codex") is not None,
            "claude_cli": shutil.which("claude") is not None,
            "litellm": True,
        },
    }


LOCAL_SERVERS = {  # local only: these probes never leave 127.0.0.1
    "ollama": ("http://127.0.0.1:11434/api/tags", "models", "name"),
    "lmstudio": ("http://127.0.0.1:1234/v1/models", "data", "id"),
}


async def _probe_local(client: httpx.AsyncClient, url: str, key: str, field: str) -> dict[str, Any]:
    try:
        r = await client.get(url)
        r.raise_for_status()
        names = [str(m[field]) for m in r.json().get(key, []) if isinstance(m, dict) and field in m]
    except (httpx.HTTPError, ValueError, AttributeError):
        return {"running": False, "models": []}
    return {"running": True, "models": names}


@router.get("/ai/local")
async def local_models() -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=1.5) as client:
        results = await asyncio.gather(*(_probe_local(client, *v) for v in LOCAL_SERVERS.values()))
    return dict(zip(LOCAL_SERVERS, results, strict=True))


class AICheck(BaseModel):
    provider: Literal["codex_cli", "claude_cli", "litellm"]
    model: str | None = None
    api_base: str | None = None


@router.post("/ai/check")
async def check_ai(request: Request, body: AICheck) -> dict[str, Any]:
    from linkit_all.providers import ProviderError, get_provider

    cfg = SearchConfig.model_validate(
        {
            "ai": {
                "provider": body.provider,
                "model": body.model or None,
                "api_base": body.api_base or None,
            }
        }
    )
    try:
        message = await get_provider(ai_settings(_settings(request), cfg)).check()
    except (ProviderError, PipelineError) as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "message": message}


# --- first-run setup: what the CV says, and writing what the user confirmed ---------------

# Non-sensitive keys the model may fill when the rules found nothing -> AiFill field.
_AI_KEYS = {
    "profile.full_name": "full_name",
    "profile.email": "email",
    "profile.phone": "phone",
    "profile.location": "location",
    "profile.skills": "skills",
    "answers.current_company": "current_company",
    "answers.current_title": "current_title",
    "answers.linkedin": "linkedin",
    "answers.github": "github",
    "answers.portfolio": "portfolio",
}
_AI_CV_CHARS = 30000


class AiFill(BaseModel):
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    skills: list[str] = []
    current_company: str = ""
    current_title: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""


def _cv_file(request: Request) -> Path | None:
    _, cv = load_fields(_db(request))
    path = Path(cv) if cv else None
    return path if path is not None and path.is_file() else None


def _cv_read(cv: Path) -> tuple[list[str], list[str]]:
    """(segment texts in order, hyperlink targets) of the stored CV."""
    from linkit_all.core.infer import cv_links
    from linkit_all.tailor.pipeline import cv_segments as read_segments

    return [s.text for s in read_segments(cv)], cv_links(cv)


def _ai_file(cv: Path) -> Path:
    return cv.parent / "infer_ai.json"


def _cv_stamp(cv: Path) -> str:
    return hashlib.sha256(cv.read_bytes()).hexdigest()


def _saved_ai(cv: Path) -> dict[str, Any]:
    """The saved gap-fill result, valid only for the exact CV file it was made from."""
    try:
        data = json.loads(_ai_file(cv).read_text("utf-8"))
        stamp = _cv_stamp(cv)
    except (OSError, ValueError):
        return {}
    if isinstance(data, dict) and data.get("cv") == stamp and isinstance(data.get("values"), dict):
        return {k: v for k, v in data["values"].items() if k in _AI_KEYS}
    return {}


def _infer_payload(
    cv: Path | None, rules: dict[str, InferredValue] | None = None
) -> dict[str, Any]:
    values: dict[str, InferredValue] = {}
    if cv is not None:
        if rules is None:
            texts, links = _cv_read(cv)
            rules = infer(read_cv(texts, links), date.today())
        values = dict(rules)
        for key, value in _saved_ai(cv).items():
            if key not in values:
                values[key] = InferredValue(value=value, source="ai", level="suggest", check=True)
    where = str(values["answers.country"].value) if "answers.country" in values else ""
    country = country_preset(where)
    track: Track = "tech" if "track" in values and values["track"].value == "tech" else "general"
    return {
        "values": {k: v.model_dump(mode="json") for k, v in values.items()},
        "country": asdict(country),
        "sources": source_preset(country, track),
        "has_cv": cv is not None,
    }


@router.get("/infer")
def get_infer(request: Request) -> dict[str, Any]:
    """What LinKit read from the CV (plus the saved AI gap-fill). Writes nothing."""
    return _infer_payload(_cv_file(request))


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


@router.post("/infer/ai-fill")
async def infer_ai_fill(request: Request) -> dict[str, Any]:
    """One model call for the non-sensitive keys the rules missed. Values must appear in the CV."""
    from linkit_all.providers import ProviderError, get_provider
    from linkit_all.providers.base import render

    cv = _cv_file(request)
    if cv is None:
        raise HTTPException(404, "No CV uploaded yet")
    cfg = load_search(_db(request)) or SearchConfig()
    if cfg.ai.provider is None:
        raise HTTPException(409, "Connect an AI first (Setup, AI connection)")
    texts, links = await asyncio.to_thread(_cv_read, cv)
    rules = infer(read_cv(texts, links), date.today())
    wanted = [k for k in _AI_KEYS if k not in rules]
    if wanted:
        cv_text = "\n".join(texts)[:_AI_CV_CHARS]
        prompt = render("infer_fill.j2", wanted=[_AI_KEYS[k] for k in wanted], cv=cv_text)
        try:
            provider = get_provider(ai_settings(_settings(request), cfg))
            got = (await provider.complete(prompt, AiFill, use_cache=False)).model_dump()
        except PipelineError as e:
            raise HTTPException(409, str(e)) from e
        except ProviderError as e:
            raise HTTPException(502, str(e)) from e
        blob = _norm("\n".join([*texts, *links]))
        kept: dict[str, Any] = {}
        for key in wanted:
            value = got[_AI_KEYS[key]]
            if isinstance(value, list):  # skills: each item must be in the CV
                value = [x for x in value if x.strip() and _norm(x) in blob]
            elif not (value.strip() and _norm(value) in blob):
                value = ""
            if value:
                kept[key] = value
        _ai_file(cv).write_text(json.dumps({"cv": _cv_stamp(cv), "values": kept}), "utf-8")
    return _infer_payload(cv, rules)


class InferApply(BaseModel):
    values: dict[str, Any] = {}
    where: list[str] | None = None
    remote: bool | None = None
    track: Track | None = None


_PROFILE_KEYS = {f"profile.{k}" for k in ProfileFields.model_fields}
_ANSWER_KEYS = {f"answers.{k}" for k in ApplicationAnswers.model_fields}
_SEARCH_KEYS = {"search.queries", "filters.seniority", "filters.title_exclude"}


def _problem(e: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors())


@router.post("/infer/apply")
def apply_infer(request: Request, body: InferApply) -> dict[str, Any]:
    """Write only the confirmed values (and the where/remote/track choices); return /status."""
    values = body.values
    unknown = sorted(set(values) - _PROFILE_KEYS - _ANSWER_KEYS - _SEARCH_KEYS)
    if unknown:
        raise HTTPException(422, f"Unknown setting: {unknown[0]}")
    db = _db(request)
    fields, _ = load_fields(db)
    with db() as s:
        profile = s.get(Profile, 1)
        answers_now = ApplicationAnswers.model_validate(profile.answers if profile else {})
    profile_new = {k[len("profile.") :]: v for k, v in values.items() if k in _PROFILE_KEYS}
    answers_new = {k[len("answers.") :]: v for k, v in values.items() if k in _ANSWER_KEYS}
    data = (load_search(db) or SearchConfig()).model_dump()
    for key in _SEARCH_KEYS & set(values):
        section, name = key.split(".")
        data[section][name] = values[key]

    where = [w.strip() for w in body.where or [] if w.strip()]
    country = country_preset("")
    if where:
        places = [*where, *(["Remote"] if body.remote else [])]
        data["search"]["locations"] = places
        data["filters"]["locations"] = [p.lower() for p in places]
        country = next((p for w in where if (p := country_preset(w)).name), country)
        if country.name:
            if country.jobspy:
                data["sources"]["jobspy_country"] = country.jobspy
            data["filters"]["salary_currency"] = country.currency
            if not answers_now.salary_currency:
                answers_new.setdefault("salary_currency", country.currency)
    if body.remote is not None:
        data["filters"]["work_modes"] = list(WORK_MODES) if body.remote else ["hybrid", "onsite"]
    try:
        fields_out = ProfileFields.model_validate({**fields.model_dump(), **profile_new})
        answers_out = ApplicationAnswers.model_validate({**answers_now.model_dump(), **answers_new})
        if where or body.track:
            if not country.name:
                country = country_preset(answers_out.country)
            preset = source_preset(country, body.track or "general")
            src = data["sources"]
            src["jobspy"], src["regional"] = preset["jobspy"], preset["regional"]
            src["enabled"] += [x for x in preset["enabled"] if x not in src["enabled"]]
            default = SourcesSection(telegram_channels=list(DEFAULT_TELEGRAM_CHANNELS))
            if src["telegram_channels"] == default.telegram_channels:  # never edited
                src["telegram_channels"] = preset["telegram_channels"]
        cfg_out = SearchConfig.model_validate(data)
    except ValidationError as e:
        raise HTTPException(422, _problem(e)) from e
    if profile_new or answers_new:
        save_fields(db, fields_out)  # also creates the profile row the answers live on
    if answers_new:
        with db.begin() as s:
            s.get_one(Profile, 1).answers = answers_out.model_dump()
    save_search(db, cfg_out)
    return status(request)


# --- jobs ---------------------------------------------------------------------


def _scores(j: Job) -> tuple[int | None, int | None]:
    trust = j.data.get("trust") or {}
    return (trust.get("scam") or {}).get("score"), (trust.get("ghost") or {}).get("score")


def _row(j: Job, filter_event: FilterEvent | None = None) -> dict[str, Any]:
    scam, ghost = _scores(j)
    why = job_reason(j, filter_event)
    return {"scam_score": scam, "ghost_score": ghost,
            "reason": why[0] if why else None, "reason_code": why[1] if why else None,
            "reason_params": why[2] if why else {},
            "id": j.id, "title": j.title, "company": j.company, "location": j.location,
            "source": j.source, "state": j.state, "tier": j.tier, "score": j.score,
            "rank": j.data.get("rank"), "remote": j.data.get("remote"), "ai": j.data.get("ai"),
            "posted_at": j.posted_at.isoformat() if j.posted_at else None}  # fmt: skip


def _last_drops(s: Session) -> dict[int, FilterEvent]:
    """The event that filtered out each currently filtered-out job: one query, not one per row."""
    latest = (
        select(func.max(JobEvent.id))
        .join(Job, Job.id == JobEvent.job_id)
        .where(JobEvent.to_state == JobState.filtered_out, Job.state == JobState.filtered_out)
        .group_by(JobEvent.job_id)
    )
    rows = s.execute(
        select(JobEvent.job_id, JobEvent.message, JobEvent.code, JobEvent.params).where(
            JobEvent.id.in_(latest)
        )
    )
    return {job_id: (message, code, params) for job_id, message, code, params in rows}


@router.get("/jobs")
def list_jobs(
    request: Request,
    state: JobState | None = None,
    tier: Tier | None = None,
    source: str | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    query = select(Job)
    if state:
        query = query.where(Job.state == state)
    if tier:
        query = query.where(Job.tier == tier)
    if source:
        query = query.where(Job.source == source)
    if q:
        like = f"%{q}%"
        query = query.where(
            Job.title.ilike(like) | Job.company.ilike(like) | Job.location.ilike(like)
        )
    with _db(request)() as s:
        jobs = list(s.scalars(query.limit(20000)))
        drops = _last_drops(s) if any(j.state == JobState.filtered_out for j in jobs) else {}
    jobs.sort(key=lambda j: (-(j.score or 0), -(j.data.get("rank") or 0)))
    return [_row(j, drops.get(j.id)) for j in jobs]


def _tailoring(cv: TailoredCV | None) -> dict[str, Any] | None:
    """The newest tailored CV as a red-line: what changed, what was refused, the layout check."""
    if cv is None:
        return None
    if cv.verify and not cv.verify.get("ok", True):
        status = "rolled_back"  # the layout check failed: the original CV was kept
    else:
        status = "tailored" if cv.applied else "unchanged"
    keys = ("segment_id", "old_text", "new_text", "reason")
    return {
        "created_at": cv.created_at.isoformat(),
        "status": status,
        "patches": [{k: p.get(k) for k in keys} for p in cv.applied],
        "rejected": cv.rejected,
        "verify": cv.verify or None,
    }


@router.get("/jobs/{job_id}")
def job_detail(request: Request, job_id: int) -> dict[str, Any]:
    with _db(request)() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        events = list(s.scalars(select(JobEvent).filter_by(job_id=job_id).order_by(JobEvent.id)))
        drop = next((e for e in reversed(events) if e.to_state == JobState.filtered_out), None)
        salary = {k: job.data.get(f"salary_{k}") for k in ("min", "max", "currency", "interval")}
        history = [
            {"id": e.id, "at": e.at.isoformat(), "from": e.from_state, "to": e.to_state,
             "message": e.message, "code": e.code, "params": e.params,
             "screenshots": len(e.artifacts)}
            for e in events
        ]  # fmt: skip
        tailored = s.scalars(
            select(TailoredCV).filter_by(job_id=job_id).order_by(TailoredCV.id.desc())
        ).first()
        return {
            **_row(job, (drop.message, drop.code, drop.params) if drop else None),
            "tailoring": _tailoring(tailored),
            "url": job.url,
            "description": job.description,
            "ats": job.ats,
            "apply_url": job.data.get("apply_url"),
            "ai": job.data.get("ai"),
            "trust": job.data.get("trust"),
            "filled": job.data.get("filled"),
            "extra": job.data.get("extra") or {},
            "email_sent": job.data.get("email_sent"),
            "salary": salary,
            "events": history,
        }


@router.get("/jobs/{job_id}/tailored.pdf")
def tailored_pdf(request: Request, job_id: int) -> FileResponse:
    with _db(request)() as s:
        cv = s.scalars(
            select(TailoredCV).filter_by(job_id=job_id).order_by(TailoredCV.id.desc())
        ).first()
        if cv is None:
            raise HTTPException(404, "No tailored CV for this job")
        path = Path(cv.pdf_path)
    return _data_file(request, path, "application/pdf")


@router.get("/jobs/{job_id}/events/{event_id}/screenshot/{n}")
def event_screenshot(request: Request, job_id: int, event_id: int, n: int) -> FileResponse:
    with _db(request)() as s:
        event = s.get(JobEvent, event_id)
        if event is None or event.job_id != job_id or not 0 <= n < len(event.artifacts):
            raise HTTPException(404)
        path = Path(event.artifacts[n])
    return _data_file(request, path)


class JobAction(BaseModel):
    ids: list[int]
    action: Literal["approve", "reject"]


@router.post("/jobs/actions")
def job_actions(request: Request, body: JobAction) -> dict[str, Any]:
    """approve: review/low tier -> apply queue; reject: -> skipped."""
    target = JobState.queued_apply if body.action == "approve" else JobState.skipped
    done, errors = 0, {}
    with _db(request).begin() as s:
        for job_id in body.ids:
            job = s.get(Job, job_id)
            if job is None:
                errors[job_id] = "not found"
                continue
            try:
                transition(
                    s, job, target, f"you chose {body.action} in the UI",
                    code=f"chose_{body.action}",
                )  # fmt: skip
                done += 1
            except InvalidTransition as e:
                errors[job_id] = str(e)
    return {"done": done, "errors": errors}


class TrustAction(BaseModel):
    action: Literal["not_scam", "report"]


class GhostFilter(BaseModel):
    threshold: int = Field(ge=1, le=100)


def _save_cfg(s: Session, cfg: SearchConfig) -> None:
    s.merge(SearchConfigRow(id=1, data=cfg.model_dump()))


def _add_company(names: list[str], company: str) -> None:
    if norm_company(company) not in {norm_company(c) for c in names}:
        names.append(company)


@router.post("/jobs/{job_id}/trust")
def job_trust(request: Request, job_id: int, body: TrustAction) -> dict[str, Any]:
    """not_scam: allow-list the company, re-check on next rank; report: blacklist the company."""
    with _db(request).begin() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        row = s.get(SearchConfigRow, 1)
        cfg = SearchConfig.model_validate(row.data) if row else SearchConfig()
        if body.action == "not_scam":
            _add_company(cfg.trust.allow_companies, job.company)
            if job.state == JobState.filtered_out:
                job.data = {k: v for k, v in job.data.items() if k != "trust_filter"}
                transition(s, job, JobState.enriched,
                           "you marked this company as not a scam: checked again",
                           code="trust_restored")  # fmt: skip
        else:
            _add_company(cfg.filters.company_blacklist, job.company)
            if job.state in (JobState.discovered, JobState.enriched):
                target = JobState.filtered_out
            elif job.state in (JobState.applying, JobState.applied):
                target = job.state  # already being applied to: only the blacklist changes
            else:
                target = JobState.skipped
            if job.state == JobState.filtered_out:
                job.data = {**job.data, "company_rule": True}  # keep it out on re-checks
            elif target != job.state:
                transition(s, job, target, "you reported this posting", code="trust_reported")
        _save_cfg(s, cfg)
        return {"state": job.state}


@router.post("/jobs/trust/filter-ghost")
def filter_ghost(request: Request, body: GhostFilter) -> dict[str, int]:
    """Filter out (or skip, where filtering is not allowed) jobs at or above a ghost score."""
    count = 0
    with _db(request).begin() as s:
        for job in s.scalars(select(Job).where(Job.state.in_(GHOST_FILTERABLE))):
            ghost = ((job.data.get("trust") or {}).get("ghost") or {}).get("score")
            if ghost is None or ghost < body.threshold:
                continue
            filtered = can_transition(job.state, JobState.filtered_out)
            if filtered:
                job.data = {**job.data, "trust_filter": "ghost"}
            transition(
                s, job, JobState.filtered_out if filtered else JobState.skipped,
                f"looks like a ghost job (score {ghost}): you filtered ghost jobs in the UI",
                code="ghost_suspected", params={"score": ghost},
            )  # fmt: skip
            count += 1
    return {"count": count}


# --- runs, report, events -----------------------------------------------------------


@router.get("/runs")
def list_runs(request: Request) -> dict[str, Any]:
    with _db(request)() as s:
        runs = s.scalars(select(Run).order_by(Run.id.desc()).limit(20))
        recent = [{"id": r.id, "status": r.status, "started_at": r.started_at.isoformat(),
                   "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                   "pause_reason": r.pause_reason, "stats": r.stats} for r in runs]  # fmt: skip
    return {"current": _runner(request).state.as_dict(), "recent": recent, "stages": STAGES}


class RunRequest(BaseModel):
    stages: list[str] = list(STAGES)
    new: bool = False


@router.post("/runs", status_code=202)
async def start_run(request: Request, body: RunRequest) -> dict[str, Any]:
    if _user_browser(request).is_open:  # same Chrome profile: close the window first
        raise HTTPException(409, "Close the app browser window before starting a run")
    try:
        return _runner(request).start(body.stages, body.new).as_dict()
    except RunBusy as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/runs/cancel")
async def cancel_run(request: Request) -> dict[str, bool]:
    return {"cancelled": _runner(request).cancel()}


@router.get("/report")
def report(
    request: Request, run_id: int | None = None, since: date | None = None
) -> dict[str, Any]:
    with _db(request)() as s:
        return build_report(s, run_id, since)


def _attachment(body: str | bytes, media_type: str, filename: str) -> Response:
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/report/export.csv")
def report_csv(request: Request, run_id: int | None = None, since: date | None = None) -> Response:
    with _db(request)() as s:
        return _attachment(export_csv(s, run_id, since), "text/csv", "linkit-report.csv")


@router.get("/report/export.pdf")
def report_pdf(request: Request, run_id: int | None = None, since: date | None = None) -> Response:
    with _db(request)() as s:
        return _attachment(export_pdf(s, run_id, since), "application/pdf", "linkit-report.pdf")


@router.websocket("/events")
async def events(ws: WebSocket) -> None:
    bus: EventBus = ws.app.state.bus
    await ws.accept()
    q = bus.subscribe()
    try:
        for event in list(bus.recent):
            await ws.send_json(event)
        if bus.last_shot is not None:
            await ws.send_json(bus.last_shot)
        while True:
            await ws.send_json(await q.get())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(q)


# --- application answers and the Action Center ---------------------------------------


@router.get("/profile/answers")
def get_answers(request: Request) -> ApplicationAnswers:
    with _db(request)() as s:
        profile = s.get(Profile, 1)
        return ApplicationAnswers.model_validate(profile.answers if profile else {})


@router.put("/profile/answers")
def put_answers(request: Request, answers: ApplicationAnswers) -> ApplicationAnswers:
    with _db(request).begin() as s:
        profile = s.get(Profile, 1)
        if profile is None:
            raise HTTPException(409, "Save your profile first")
        profile.answers = answers.model_dump()
    return answers


def _action(item: ActionItem, job: Job) -> dict[str, Any]:
    job_summary = {
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "score": job.score,
        "url": job.url,
        "apply_url": job.data.get("apply_url") or job.url,
    }
    return {
        "id": item.id,
        "kind": item.kind,
        "status": item.status,
        "message": item.message,
        "code": item.code,
        "params": item.params,
        "questions": [{**q, "category": _category(q)} for q in item.questions],
        "answers": item.answers,
        "screenshots": len(item.artifacts),
        "created_at": item.created_at.isoformat(),
        "job": job_summary,
        **({"email_draft": job.data.get("email_draft")} if item.kind == "confirm_email" else {}),
    }


@router.get("/actions")
def list_actions(
    request: Request, status: ActionStatus = ActionStatus.open
) -> list[dict[str, Any]]:
    with _db(request)() as s:
        rows = s.execute(
            select(ActionItem, Job).join(Job, Job.id == ActionItem.job_id)
            .where(ActionItem.status == status).order_by(ActionItem.id.desc())
        ).all()  # fmt: skip
        return [_action(item, job) for item, job in rows]


@router.get("/actions/{item_id}/screenshot/{n}")
def action_screenshot(request: Request, item_id: int, n: int) -> FileResponse:
    with _db(request)() as s:
        item = s.get(ActionItem, item_id)
        if item is None or not 0 <= n < len(item.artifacts):
            raise HTTPException(404)
        path = Path(item.artifacts[n])
    return _data_file(request, path)


@router.post("/actions/{item_id}/browser", status_code=201)
async def open_app_browser(request: Request, item_id: int) -> dict[str, Any]:
    """Open the job's apply page in a headed Chrome window on the profile the apply stage used,
    so the user can sign in / solve a CAPTCHA / enter a 2FA code themselves. Nothing is typed."""
    with _db(request)() as s:
        item = s.get(ActionItem, item_id)
        job = s.get(Job, item.job_id) if item else None
        if item is None or job is None:
            raise HTTPException(404, "Action item not found")
        url, ats = job.data.get("apply_url") or job.url, job.ats
    browser = _user_browser(request)
    if _runner(request).state.running:  # a run owns the Chrome profile
        raise HTTPException(409, "A run is in progress: wait for it, or cancel it")
    if browser.is_open:
        raise HTTPException(409, "The app browser is already open: close its window first")
    try:
        await browser.open(profile_dir(_settings(request), ats), url, item_id)
    except Exception as e:
        raise HTTPException(503, f"Could not open Chrome: {str(e).splitlines()[0][:200]}") from e
    return {"open": True, "item_id": item_id}


@router.delete("/actions/{item_id}/browser", status_code=204)
async def close_app_browser(request: Request, item_id: int) -> None:
    await _user_browser(request).close()


@router.post("/linkedin/signin", status_code=201)
async def linkedin_signin(request: Request) -> dict[str, Any]:
    """Open the LinkedIn login page in the app browser (its own `linkedin` profile) so the user
    signs in themselves. Nothing is typed or clicked by the app."""
    browser = _user_browser(request)
    if _runner(request).state.running:  # a run may be using the profile
        raise HTTPException(409, "A run is in progress: wait for it, or cancel it")
    if browser.is_open:
        raise HTTPException(409, "The app browser is already open: close its window first")
    try:
        await browser.open(
            profile_dir(_settings(request), "linkedin"), "https://www.linkedin.com/login", 0
        )
    except Exception as e:
        raise HTTPException(503, f"Could not open Chrome: {str(e).splitlines()[0][:200]}") from e
    return {"open": True, "item_id": 0}


@router.get("/linkedin/session")
async def linkedin_session(request: Request) -> dict[str, str]:
    """Is the saved LinkedIn sign-in still good? Looks at the feed (headless unless the setting says
    otherwise)."""
    from linkit_all.sources.linkedin_posts.session import SessionError, check_session

    if _runner(request).state.running:
        raise HTTPException(409, "A run is in progress: wait for it, or cancel it")
    headless = (load_search(_db(request)) or SearchConfig()).sources.linkedin_headless
    try:
        state = await check_session(_settings(request), headless, _user_browser(request))
    except SessionError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:
        raise HTTPException(503, f"Could not open Chrome: {str(e).splitlines()[0][:200]}") from e
    return {"state": state}


def _entry(e: AnswerEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "question": e.question,
        "answer": e.answer,
        "source": e.source,
        "sensitive": e.sensitive,
        "uses": e.uses,
        "updated_at": e.updated_at.isoformat(),
    }


AnswerValue = str | list[str] | bool


def _check_answer(v: AnswerValue) -> AnswerValue:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        v = v.strip()
    if not v or (isinstance(v, list) and not any(x.strip() for x in v)):
        raise ValueError("answer cannot be empty")
    return v


class AnswerEdit(BaseModel):
    question: str | None = None
    answer: AnswerValue

    @field_validator("question")
    @classmethod
    def _question(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("question cannot be empty")
        return v and v.strip()

    @field_validator("answer")
    @classmethod
    def _answer(cls, v: AnswerValue) -> AnswerValue:
        return _check_answer(v)


@router.get("/answers")
def list_answers(request: Request) -> list[dict[str, Any]]:
    with _db(request)() as s:
        rows = s.scalars(
            select(AnswerEntry).order_by(AnswerEntry.updated_at.desc(), AnswerEntry.id.desc())
        )
        return [_entry(e) for e in rows]


@router.put("/answers/{answer_id}")
def edit_answer(request: Request, answer_id: int, body: AnswerEdit) -> dict[str, Any]:
    with _db(request).begin() as s:
        entry = s.get(AnswerEntry, answer_id)
        if entry is None:
            raise HTTPException(404, "Answer not found")
        if body.question is not None:
            entry.question = body.question
        entry.answer = body.answer
        entry.source = "user"  # a hand edit makes it the user's own answer
        entry.updated_at = utcnow()
        s.flush()
        return _entry(entry)


@router.delete("/answers/{answer_id}", status_code=204)
def delete_answer(request: Request, answer_id: int) -> None:
    with _db(request).begin() as s:
        entry = s.get(AnswerEntry, answer_id)
        if entry is None:
            raise HTTPException(404, "Answer not found")
        s.delete(entry)


class ActionAnswers(BaseModel):
    answers: dict[str, Any]  # question label -> the user's answer


class ActionDecision(BaseModel):
    decision: Literal["answer", "confirm", "retry", "applied_by_hand", "skip"]
    answers: dict[str, Any] = {}
    remember: dict[str, Any] = {}  # profile answers to keep ("Always"); see REMEMBER_KEYS


# Profile answers the Action Center may save for good (agreements and standing preferences).
REMEMBER_KEYS = frozenset({
    "acknowledge_privacy", "acknowledge_legal", "notice_period", "willing_to_relocate",
    "eeo_gender", "eeo_race", "eeo_hispanic", "eeo_veteran", "eeo_disability",
})  # fmt: skip
# Park codes that were renamed: open items with the old code count as the new one.
CODE_ALIASES = {"needs_email": ("needs_email", "email_not_connected")}
SAME_QUESTION = 92  # rapidfuzz token_sort_ratio at which two question labels are one question


def _remembered(remember: dict[str, Any]) -> dict[str, Any]:
    """The validated `remember` values; 422 for a key outside REMEMBER_KEYS or a bad value."""
    if bad := sorted(set(remember) - REMEMBER_KEYS):
        raise HTTPException(422, f"Cannot remember: {', '.join(bad)}")
    try:
        return ApplicationAnswers.model_validate(remember).model_dump(include=set(remember))
    except ValidationError as e:
        fields = ", ".join(str(err["loc"][0]) for err in e.errors())
        raise HTTPException(422, f"Invalid value for: {fields}") from None


def _save_remembered(s: Session, values: dict[str, Any]) -> None:
    if not values:
        return
    profile = s.get(Profile, 1)
    if profile is None:
        raise HTTPException(409, "Save your profile first")
    profile.answers = ApplicationAnswers.model_validate({**profile.answers, **values}).model_dump()


def _label_key(label: str) -> str:
    """Lowercase, collapse whitespace, drop trailing `*`, `:` and `?`."""
    return " ".join(label.lower().split()).rstrip("*:? ")


def _category(q: dict[str, Any]) -> str | None:
    """The sensitive category of a stored question (acknowledge_privacy, ...) or None."""
    flagged = Question(
        key="", label=q["label"], kind=q.get("kind") or "text", options=q.get("options") or []
    )
    return sensitive_category(flagged)


def _is_sensitive(q: dict[str, Any]) -> bool:
    return bool(q.get("sensitive")) or _category(q) is not None


def _same_label(a: str, b: str, exact: bool = False) -> bool:
    """a and b are `_label_key`s. `exact`: sensitive questions never match by similarity."""
    return a == b or (not exact and fuzz.token_sort_ratio(a, b) >= SAME_QUESTION)


def _unanswered(item: ActionItem) -> list[dict[str, Any]]:
    return [q for q in item.questions if item.answers.get(q["label"]) in (None, "", [])]


def _close_item(s: Session, item: ActionItem, job: Job, decision: str) -> None:
    """Apply an Action Center decision to the item and its job."""
    if decision == "confirm":
        job.data = {**job.data, "submit_confirmed": True}
    if decision == "skip":
        transition(s, job, JobState.skipped, "you skipped it in the Action Center", code="skipped")
    elif decision == "applied_by_hand":
        transition(s, job, JobState.applying, "you applied by hand", code="applied_by_hand")
        transition(s, job, JobState.applied, "you applied by hand", code="applied_by_hand")
    else:
        transition(
            s, job, JobState.queued_apply, f"Action Center: {decision}",
            code=f"decision_{decision}",
        )  # fmt: skip
    item.status = ActionStatus.dismissed if decision == "skip" else ActionStatus.resolved
    item.resolved_at = utcnow()


class RetryCode(BaseModel):
    code: str = Field(min_length=1)


@router.post("/actions/retry-code")
def retry_code(request: Request, body: RetryCode) -> dict[str, int]:
    """Requeue every open item parked with this code (e.g. after the user connected their email)."""
    codes = CODE_ALIASES.get(body.code, (body.code,))
    count = 0
    with _db(request).begin() as s:
        items = s.scalars(
            select(ActionItem)
            .where(ActionItem.status == ActionStatus.open, ActionItem.code.in_(codes))
            .order_by(ActionItem.id)
        ).all()
        for item in items:
            job = s.get_one(Job, item.job_id)
            if can_transition(job.state, JobState.queued_apply):
                _close_item(s, item, job, "retry")
                count += 1
    return {"count": count}


@router.get("/actions/groups")
def action_groups(request: Request) -> list[dict[str, Any]]:
    """Open questions grouped by label, so one answer can serve every item that asks it."""
    groups: list[dict[str, Any]] = []
    with _db(request)() as s:
        items = s.scalars(
            select(ActionItem)
            .where(
                ActionItem.status == ActionStatus.open,
                ActionItem.kind == ActionKind.unknown_question,
            )
            .order_by(ActionItem.id)
        )
        for item in items:
            for q in _unanswered(item):
                key = _label_key(q["label"])
                options = sorted(str(o).lower() for o in q.get("options") or [])
                sensitive = _is_sensitive(q)
                # same wording AND same kind/options: the one answer must fit every item
                group = next(
                    (
                        g for g in groups
                        if g["kind"] == q.get("kind") and g["_options"] == options
                        and _same_label(g["_key"], key, sensitive or g["sensitive"])
                    ),
                    None,
                )  # fmt: skip
                if group is None:
                    group = {
                        "label": q["label"].strip(), "sensitive": False, "kind": q.get("kind"),
                        "options": q.get("options") or [], "item_ids": [],
                        "_key": key, "_options": options,
                    }  # fmt: skip
                    groups.append(group)
                group["sensitive"] = group["sensitive"] or sensitive
                if item.id not in group["item_ids"]:
                    group["item_ids"].append(item.id)
    groups.sort(key=lambda g: -len(g["item_ids"]))  # stable: ties keep first-seen order
    return [
        {**{k: v for k, v in g.items() if not k.startswith("_")}, "count": len(g["item_ids"])}
        for g in groups
    ]


class GroupAnswer(BaseModel):
    item_ids: list[int] = Field(min_length=1)
    label: str = Field(min_length=1)
    value: AnswerValue
    remember: dict[str, Any] = {}

    @field_validator("value")
    @classmethod
    def _value(cls, v: AnswerValue) -> AnswerValue:
        return _check_answer(v)


@router.post("/actions/answer-group")
def answer_group(request: Request, body: GroupAnswer) -> dict[str, int]:
    """Give one answer to the matching question in each listed open item. An item with no other
    required question left is requeued; the rest keep the partial answer and stay open. The
    answer is typed by the user, so sensitive questions are fine; the AI is never involved."""
    remembered = _remembered(body.remember)
    key = _label_key(body.label)
    label_sensitive = _is_sensitive({"label": body.label})
    resolved = still_open = skipped = 0
    sensitive = False
    with _db(request).begin() as s:
        for item_id in dict.fromkeys(body.item_ids):
            item = s.get(ActionItem, item_id)
            job = s.get(Job, item.job_id) if item else None
            if (
                item is None or job is None
                or item.status != ActionStatus.open or item.kind != ActionKind.unknown_question
                or not can_transition(job.state, JobState.queued_apply)
            ):  # fmt: skip
                skipped += 1
                continue
            hits = [
                q for q in _unanswered(item)
                if _same_label(key, _label_key(q["label"]), label_sensitive or _is_sensitive(q))
            ]  # fmt: skip
            if not hits:
                skipped += 1
                continue
            item.answers = {**item.answers, **{q["label"]: body.value for q in hits}}
            sensitive = sensitive or any(_is_sensitive(q) for q in hits)
            if any(q.get("required") for q in _unanswered(item)):
                still_open += 1
            else:
                _close_item(s, item, job, "answer")
                resolved += 1
        if resolved + still_open:
            AnswerBank(_db(request)).save(
                body.label.strip(), body.value, "user", sensitive, session=s
            )
            _save_remembered(s, remembered)
    return {"resolved": resolved, "still_open": still_open, "skipped": skipped}


class EmailDraftEdit(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)

    @field_validator("subject")
    @classmethod
    def _one_line(cls, v: str) -> str:
        if "\r" in v or "\n" in v:
            raise ValueError("the subject must be a single line")
        if not v.strip():
            raise ValueError("the subject is empty")
        return v.strip()

    @field_validator("body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("the body is empty")
        return v


@router.put("/actions/{item_id}/email-draft")
def edit_email_draft(request: Request, item_id: int, body: EmailDraftEdit) -> dict[str, Any]:
    """Edit the application email waiting in the Action Center; confirming sends this text."""
    with _db(request).begin() as s:
        item = s.get(ActionItem, item_id)
        if item is None or item.status != ActionStatus.open or item.kind != "confirm_email":
            raise HTTPException(404, "No open email confirmation with that id")
        job = s.get_one(Job, item.job_id)
        draft = job.data.get("email_draft")
        if not isinstance(draft, dict):
            raise HTTPException(409, "This job has no email draft")
        if body.body != draft.get("body"):
            draft = {k: v for k, v in draft.items() if k != "problem"}  # the user wrote it
        draft = {**draft, "subject": body.subject, "body": body.body}
        job.data = {**job.data, "email_draft": draft}
        item.params = {**item.params, "subject": body.subject}
        return draft


@router.post("/actions/{item_id}")
def resolve_action(request: Request, item_id: int, body: ActionDecision) -> dict[str, Any]:
    """answer: save to the answer bank and requeue; confirm: submit on the next apply run;
    retry: requeue as is; applied_by_hand: you submitted it yourself; skip: drop the job."""
    db = _db(request)
    remembered = _remembered(body.remember) if body.decision == "answer" else {}
    with db.begin() as s:  # one transaction: a refused request writes nothing
        item = s.get(ActionItem, item_id)
        if item is None or item.status != ActionStatus.open:
            raise HTTPException(404, "No open item with that id")
        job = s.get_one(Job, item.job_id)
        if body.decision == "answer":
            questions = {q["label"]: q for q in item.questions}
            given = {
                k: v for k, v in body.answers.items() if k in questions and v not in (None, "", [])
            }
            have = {**item.answers, **given}  # answers kept earlier from a group count too
            missing = [
                label for label, q in questions.items()
                if q.get("required") and have.get(label) in (None, "", [])
            ]  # fmt: skip
            if missing:
                raise HTTPException(422, f"Please answer: {missing[0]}")
            bank = AnswerBank(db)
            for label, value in given.items():
                bank.save(label, value, "user", bool(questions[label].get("sensitive")), s)
            item.answers = have
            _save_remembered(s, remembered)
        _close_item(s, item, job, body.decision)
        return {"job_state": job.state}


@router.get("/live/screenshot")
def live_screenshot(request: Request) -> FileResponse:
    """The page the apply stage is working on right now (a JPEG every ~3 s)."""
    path = fresh_live_shot(_settings(request))
    if path is None:
        raise HTTPException(404)
    return _data_file(request, path, "image/jpeg", {"Cache-Control": "no-store"})


# --- vault --------------------------------------------------------------------
# Passphrases and secrets travel in POST bodies only and never appear in an error message.


class Passphrase(BaseModel):
    passphrase: str


class Unlock(Passphrase):
    remember: bool = True


def _vault_errors(fn: Any) -> Any:
    """Run a vault call, mapping its errors to plain HTTP errors."""
    try:
        return fn()
    except VaultLocked:
        raise HTTPException(423, "The vault is locked") from None
    except WrongPassphrase:
        raise HTTPException(401, "Wrong passphrase") from None
    except VaultError:
        raise HTTPException(409, "The vault is not available for that") from None


@router.get("/vault")
def get_vault(request: Request) -> dict[str, Any]:
    vault = _vault(request)
    unlocked = vault.unlocked()
    entries = [
        {
            **e.__dict__,
            "created_at": e.created_at.isoformat(),
            "updated_at": e.updated_at.isoformat(),
        }
        for e in (_vault_errors(vault.entries) if unlocked else [])
    ]
    return {"initialized": vault.initialized(), "unlocked": unlocked, "entries": entries}


@router.post("/vault/create", status_code=201)
def create_vault(request: Request, body: Passphrase) -> dict[str, bool]:
    vault = _vault(request)
    if vault.initialized():
        raise HTTPException(409, "A vault already exists")
    try:
        vault.create(body.passphrase)
    except ValueError:
        raise HTTPException(422, "The passphrase must be at least 8 characters") from None
    return {"initialized": True, "unlocked": vault.unlocked()}


@router.post("/vault/unlock")
def unlock_vault(request: Request, body: Unlock) -> dict[str, bool]:
    vault = _vault(request)
    if not vault.initialized():
        raise HTTPException(409, "No vault yet: create one first")
    _vault_errors(lambda: vault.unlock(body.passphrase, body.remember))
    return {"initialized": True, "unlocked": True}


@router.post("/vault/lock")
def lock_vault(request: Request) -> dict[str, bool]:
    vault = _vault(request)
    vault.lock()
    return {"initialized": vault.initialized(), "unlocked": False}


@router.delete("/vault/entries/{entry_id}", status_code=204)
def delete_vault_entry(request: Request, entry_id: int) -> None:
    _vault_errors(lambda: _vault(request).delete(entry_id))


@router.post("/vault/entries/{entry_id}/reveal")
def reveal_vault_entry(request: Request, entry_id: int, body: Passphrase) -> dict[str, str]:
    vault = _vault(request)

    def reveal() -> str:
        if not vault.unlocked():
            raise VaultLocked
        if not vault.verify(body.passphrase):
            raise WrongPassphrase
        return vault.get(entry_id)

    try:
        return {"secret": _vault_errors(reveal)}
    except KeyError:
        raise HTTPException(404, "Entry not found") from None


@router.post("/vault/export")
def export_vault(request: Request, body: Passphrase) -> JSONResponse:
    """Every entry with its secret, as an unencrypted JSON download."""
    entries = _vault_errors(lambda: _vault(request).export(body.passphrase))
    return JSONResponse(
        entries,
        headers={
            "Content-Disposition": "attachment; filename=linkit-vault-export.json",
            "Cache-Control": "no-store",
        },
    )


# --- email (IMAP, read-only; for sign-up verification mails) -------------------
# The app password travels in the POST body only, goes straight to the vault and is never echoed.


class EmailConnect(BaseModel):
    imap_host: str | None = None
    imap_user: str | None = None
    app_password: str


def _email_target(
    request: Request, host: str | None = None, user: str | None = None
) -> tuple[SearchConfig, str, str]:
    """Config plus the effective (host, user): given value, else config, else the profile email."""
    cfg = load_search(_db(request)) or SearchConfig()
    host = (host or cfg.email.imap_host).strip().lower()
    user = (user or cfg.email.imap_user or load_fields(_db(request))[0].email).strip().lower()
    return cfg, host, user


def _unlocked_vault(request: Request) -> Vault:
    vault = _vault(request)
    if not vault.unlocked():
        raise HTTPException(423, "Unlock the vault first")
    return vault


@router.get("/email")
def get_email(request: Request) -> dict[str, Any]:
    _, host, user = _email_target(request)
    vault = _vault(request)
    connected = vault.unlocked() and any(
        e.username.lower() == user for e in _vault_errors(lambda: vault.find("imap", host))
    )
    return {
        "imap_host": host,
        "imap_user": user,
        "connected": connected,
        "vault": {"initialized": vault.initialized(), "unlocked": vault.unlocked()},
    }


@router.post("/email")
async def connect_email(request: Request, body: EmailConnect) -> dict[str, Any]:
    vault = _unlocked_vault(request)
    cfg, host, user = _email_target(request, body.imap_host, body.imap_user)
    password = "".join(body.app_password.split())  # Google shows it as "abcd efgh ijkl mnop"
    if "@" not in user:
        raise HTTPException(400, "Enter your email address")
    if not password:
        raise HTTPException(400, "Enter the app password")
    try:
        await asyncio.to_thread(check_login, host, user, password)
    except EmailLoginError as e:
        raise HTTPException(400, str(e)) from None
    _vault_errors(lambda: vault.put("imap", host, user, password))
    cfg.email.imap_host, cfg.email.imap_user = host, user
    save_search(_db(request), cfg)
    return get_email(request)


@router.post("/email/test")
async def test_email(request: Request) -> dict[str, bool]:
    vault = _unlocked_vault(request)
    cfg, _, user = _email_target(request)
    creds = _vault_errors(lambda: credentials(cfg.email, vault, user))
    if creds is None:
        raise HTTPException(404, "No email connected yet")
    try:
        await asyncio.to_thread(check_login, cfg.email.imap_host, *creds)
    except EmailLoginError as e:
        raise HTTPException(400, str(e)) from None
    return {"ok": True}


@router.post("/email/test-send")
async def test_send_email(request: Request) -> dict[str, Any]:
    """Send a short test email to the user's own address through SMTP."""
    vault = _unlocked_vault(request)
    cfg, _, user = _email_target(request)
    name = load_fields(_db(request))[0].full_name
    mail = OutgoingEmail(
        to=user,
        subject="LinKit All test",
        body="This is a test email from LinKit All. Sending works.",
    )
    try:
        msg = build_message(name, user, mail)
        message_id = await asyncio.to_thread(send, cfg.email, vault, user, msg)
    except NoCredentials:
        raise HTTPException(409, "No email connected yet") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from None
    except VaultLocked:
        raise HTTPException(423, "The vault is locked") from None
    except VaultError:
        raise HTTPException(409, "The vault is not available for that") from None
    except SmtpError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "message_id": message_id}


@router.delete("/email", status_code=204)
def disconnect_email(request: Request) -> None:
    vault = _unlocked_vault(request)
    _, host, user = _email_target(request)

    def drop() -> None:
        for e in vault.find("imap", host):
            if e.username.lower() == user:
                vault.delete(e.id)

    _vault_errors(drop)


# --- API keys (job-aggregator APIs; stored in the vault) ------------------------
# Values travel in the PUT body only. Responses carry the saved non-secret fields and, for secret
# ones, only the last 4 characters.


def _mask(value: str) -> str:
    return "••••" + value[-4:] if len(value) > 8 else "••••"


@router.get("/keys")
def list_keys(request: Request) -> list[dict[str, Any]]:
    vault = _vault(request)
    out = []
    for spec in KNOWN.values():
        saved = _vault_errors(partial(get_keys, vault, spec.name))
        out.append(
            {
                "name": spec.name,
                "label": spec.label,
                "fields": [
                    {"name": f.name, "label": f.label, "secret": f.secret} for f in spec.fields
                ],
                "signup_url": spec.signup_url,
                "note": spec.note,
                "configured": saved is not None,
                "current": {
                    f.name: _mask(saved[f.name]) if f.secret else saved[f.name]
                    for f in spec.fields
                    if saved and f.name in saved
                },
            }
        )
    return out


# --- job sources (what Setup lets the user switch on) ---------------------------------


def _describe(source: Source) -> str:
    """First sentence of the plugin module's docstring."""
    doc = " ".join((sys.modules[type(source).__module__].__doc__ or "").split("\n\n")[0].split())
    first = re.match(r".+?[.!?](?=\s|$)", doc)
    return (first.group() if first else doc)[:200]


@router.get("/sources")
def list_sources(request: Request) -> dict[str, Any]:
    """The opt-in sources (names go in `sources.enabled`) plus how many ATS platforms are known."""
    cfg = load_search(_db(request)) or SearchConfig()
    vault = _vault(request)
    found = registry(None, _settings(request).data_dir)
    out = []
    for s in found.values():
        if s.kind not in OPT_IN_KINDS:
            continue
        key = s.name if s.name in KNOWN else None  # keyed plugins are named after their provider
        out.append(
            {
                "name": s.name,
                "kind": s.kind,
                "label": getattr(s, "label", "") or s.name.replace("_", " ").title(),
                "region": getattr(s, "region", ""),
                "needs_key": key,
                "key_configured": bool(key and _vault_errors(partial(get_keys, vault, key))),
                "description": _describe(s),
                "enabled": s.is_enabled(cfg),
            }
        )
    out.sort(key=lambda o: (o["kind"], str(o["label"]).lower()))
    return {"ats_count": sum(s.kind == "ats" for s in found.values()), "sources": out}


@router.put("/keys/{name}")
def put_keys(request: Request, name: str, body: dict[str, str]) -> list[dict[str, Any]]:
    vault = _unlocked_vault(request)
    if name not in KNOWN:
        raise HTTPException(422, "Unknown provider")
    # A blank field keeps its saved value, so one field can change without retyping the rest.
    values = {
        **(_vault_errors(lambda: get_keys(vault, name)) or {}),
        **{k: v for k, v in body.items() if v.strip()},
    }
    try:
        _vault_errors(lambda: set_keys(vault, name, values))
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    return list_keys(request)


@router.delete("/keys/{name}", status_code=204)
def remove_keys(request: Request, name: str) -> None:
    vault = _unlocked_vault(request)
    if name not in KNOWN:
        raise HTTPException(422, "Unknown provider")
    _vault_errors(lambda: delete_keys(vault, name))
