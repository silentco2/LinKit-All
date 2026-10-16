"""REST API for the local UI. Everything lives under /api."""

import asyncio
import shutil
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.api.events import EventBus
from linkit_all.api.runner import PipelineRunner, RunBusy
from linkit_all.apply.answers import ApplicationAnswers
from linkit_all.apply.assist import AnswerBank
from linkit_all.apply.vault import Vault, VaultError, VaultLocked, WrongPassphrase
from linkit_all.core.config import Settings
from linkit_all.core.models import (
    ActionItem,
    ActionStatus,
    AnswerEntry,
    Job,
    JobEvent,
    JobState,
    Profile,
    Run,
    Tier,
    utcnow,
)  # fmt: skip
from linkit_all.core.profile import ProfileFields, load_fields, save_cv, save_fields
from linkit_all.core.search import SearchConfig, load_search, save_search
from linkit_all.core.state import InvalidTransition, transition
from linkit_all.core.tools import soffice_path
from linkit_all.pipeline import STAGES, PipelineError, ai_settings

router = APIRouter(prefix="/api")


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


def _data_file(request: Request, path: Path) -> FileResponse:
    """Serve a PNG, but only a file the app wrote into its own data dir."""
    path = path.resolve()
    if not path.is_relative_to(_settings(request).data_dir.resolve()) or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png")


# --- status -------------------------------------------------------------------


@router.get("/status")
def status(request: Request) -> dict[str, Any]:
    db = _db(request)
    fields, cv = load_fields(db)
    cfg = load_search(db)
    vault = _vault(request)
    with db() as s:
        states = dict(s.execute(select(Job.state, func.count()).group_by(Job.state)).all())
    return {
        "profile_ready": bool(fields.full_name and fields.email),
        "cv_ready": bool(cv),
        "search_ready": cfg is not None and bool(cfg.search.queries or cfg.sources.companies),
        "ai_ready": cfg is not None and cfg.ai.provider is not None,
        "libreoffice": soffice_path() is not None,
        "vault": {"initialized": vault.initialized(), "unlocked": vault.unlocked()},
        "states": {str(k): v for k, v in states.items()},
        "actions_open": _open_actions(db),
        "apply_live": bool(cfg and cfg.apply.live),
        "run": _runner(request).state.as_dict(),
    }


def _open_actions(db: sessionmaker[Session]) -> int:
    with db() as s:
        return s.scalar(select(func.count()).where(ActionItem.status == ActionStatus.open)) or 0


# --- profile ------------------------------------------------------------------


def _segments(cv: str) -> list[dict[str, Any]]:
    from docx import Document

    from linkit_all.tailor.docx.segments import load_segments

    return [{"id": s.id, "text": s.text} for s in load_segments(Document(cv)) if s.text.strip()]


@router.get("/profile")
def get_profile(request: Request) -> dict[str, Any]:
    fields, cv = load_fields(_db(request))
    return {
        **fields.model_dump(),
        "cv_name": cv.replace("\\", "/").rsplit("/", 1)[-1] if cv else None,
    }


@router.put("/profile")
def put_profile(request: Request, fields: ProfileFields) -> dict[str, Any]:
    save_fields(_db(request), fields)
    return get_profile(request)


@router.post("/profile/cv")
async def upload_cv(request: Request, filename: str) -> dict[str, Any]:
    """Raw DOCX bytes in the body (no multipart dependency needed)."""
    try:
        cv = save_cv(_db(request), _settings(request).data_dir, filename, await request.body())
        segments = await asyncio.to_thread(_segments, str(cv))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"cv_name": cv.name, "segments": segments}


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
    return cfg


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


class AICheck(BaseModel):
    provider: Literal["codex_cli", "claude_cli", "litellm"]
    model: str | None = None


@router.post("/ai/check")
async def check_ai(request: Request, body: AICheck) -> dict[str, Any]:
    from linkit_all.providers import ProviderError, get_provider

    cfg = SearchConfig.model_validate(
        {"ai": {"provider": body.provider, "model": body.model or None}}
    )
    try:
        message = await get_provider(ai_settings(_settings(request), cfg)).check()
    except (ProviderError, PipelineError) as e:
        return {"ok": False, "message": str(e)}
    return {"ok": True, "message": message}


# --- jobs ---------------------------------------------------------------------


def _row(j: Job) -> dict[str, Any]:
    return {"id": j.id, "title": j.title, "company": j.company, "location": j.location,
            "source": j.source, "state": j.state, "tier": j.tier, "score": j.score,
            "rank": j.data.get("rank"), "remote": j.data.get("remote"), "ai": j.data.get("ai"),
            "posted_at": j.posted_at.isoformat() if j.posted_at else None}  # fmt: skip


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
    jobs.sort(key=lambda j: (-(j.score or 0), -(j.data.get("rank") or 0)))
    return [_row(j) for j in jobs]


@router.get("/jobs/{job_id}")
def job_detail(request: Request, job_id: int) -> dict[str, Any]:
    with _db(request)() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        events = s.scalars(select(JobEvent).filter_by(job_id=job_id).order_by(JobEvent.id))
        salary = {k: job.data.get(f"salary_{k}") for k in ("min", "max", "currency", "interval")}
        history = [
            {"id": e.id, "at": e.at.isoformat(), "from": e.from_state, "to": e.to_state,
             "message": e.message, "screenshots": len(e.artifacts)}
            for e in events
        ]  # fmt: skip
        return {**_row(job), "url": job.url, "description": job.description, "ats": job.ats,
                "apply_url": job.data.get("apply_url"), "ai": job.data.get("ai"),
                "filled": job.data.get("filled"), "salary": salary, "events": history}  # fmt: skip


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
                transition(s, job, target, f"you chose {body.action} in the UI")
                done += 1
            except InvalidTransition as e:
                errors[job_id] = str(e)
    return {"done": done, "errors": errors}


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
    try:
        return _runner(request).start(body.stages, body.new).as_dict()
    except RunBusy as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/runs/cancel")
async def cancel_run(request: Request) -> dict[str, bool]:
    return {"cancelled": _runner(request).cancel()}


# Job states at or past each funnel step.
_RANKED = {JobState.ranked, JobState.scored, JobState.below_threshold, JobState.awaiting_review,
           JobState.queued_apply, JobState.tailored, JobState.applying, JobState.needs_user,
           JobState.applied, JobState.failed, JobState.skipped}  # fmt: skip
_TO_APPLY = {JobState.queued_apply, JobState.tailored, JobState.applying, JobState.needs_user,
             JobState.applied, JobState.failed}  # fmt: skip


@router.get("/report")
def report(request: Request) -> dict[str, Any]:
    with _db(request)() as s:
        states = dict(s.execute(select(Job.state, func.count()).group_by(Job.state)).all())
        tiers = dict(
            s.execute(
                select(Job.tier, func.count()).where(Job.tier.is_not(None)).group_by(Job.tier)
            ).all()
        )
        scored = s.scalar(select(func.count()).where(Job.score.is_not(None))) or 0
        by_source = s.execute(
            select(Job.source, Job.state, func.count()).group_by(Job.source, Job.state)
        ).all()
    total = sum(states.values())
    ranked = sum(states.get(x, 0) for x in _RANKED)
    sources: dict[str, dict[str, int]] = {}
    for source, state, count in by_source:
        row = sources.setdefault(source, {"total": 0})
        row["total"] += count
        row[str(state)] = count
    return {
        "funnel": [
            {"step": "Found", "count": total},
            {"step": "Passed filters", "count": ranked},
            {"step": "AI scored", "count": scored},
            {"step": "Queued to apply", "count": sum(states.get(x, 0) for x in _TO_APPLY)},
            {"step": "Applied", "count": states.get(JobState.applied, 0)},
        ],
        "tiers": {str(k): v for k, v in tiers.items()},
        "states": {str(k): v for k, v in states.items()},
        "sources": sources,
    }


@router.websocket("/events")
async def events(ws: WebSocket) -> None:
    bus: EventBus = ws.app.state.bus
    await ws.accept()
    q = bus.subscribe()
    try:
        for event in list(bus.recent):
            await ws.send_json(event)
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
        "questions": item.questions,
        "answers": item.answers,
        "screenshots": len(item.artifacts),
        "created_at": item.created_at.isoformat(),
        "job": job_summary,
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


class AnswerEdit(BaseModel):
    question: str | None = None
    answer: str | list[str] | bool

    @field_validator("question")
    @classmethod
    def _question(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("question cannot be empty")
        return v and v.strip()

    @field_validator("answer")
    @classmethod
    def _answer(cls, v: str | list[str] | bool) -> str | list[str] | bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            v = v.strip()
        if not v or (isinstance(v, list) and not any(x.strip() for x in v)):
            raise ValueError("answer cannot be empty")
        return v


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


@router.post("/actions/{item_id}")
def resolve_action(request: Request, item_id: int, body: ActionDecision) -> dict[str, Any]:
    """answer: save to the answer bank and requeue; confirm: submit on the next apply run;
    retry: requeue as is; applied_by_hand: you submitted it yourself; skip: drop the job."""
    db = _db(request)
    if body.decision == "answer":
        with db() as s:
            item = s.get(ActionItem, item_id)
            questions = {q["label"]: q for q in (item.questions if item else [])}
        missing = [
            label
            for label, q in questions.items()
            if q.get("required") and body.answers.get(label) in (None, "", [])
        ]
        if missing:
            raise HTTPException(422, f"Please answer: {missing[0]}")
        bank = AnswerBank(db)
        for label, value in body.answers.items():
            if label in questions and value not in (None, "", []):
                bank.save(label, value, "user", sensitive=bool(questions[label].get("sensitive")))
    with db.begin() as s:
        item = s.get(ActionItem, item_id)
        if item is None or item.status != ActionStatus.open:
            raise HTTPException(404, "No open item with that id")
        job = s.get_one(Job, item.job_id)
        if body.decision == "confirm":
            job.data = {**job.data, "submit_confirmed": True}
        if body.decision == "skip":
            transition(s, job, JobState.skipped, "you skipped it in the Action Center")
        elif body.decision == "applied_by_hand":
            transition(s, job, JobState.applying, "you applied by hand")
            transition(s, job, JobState.applied, "you applied by hand")
        else:
            transition(s, job, JobState.queued_apply, f"Action Center: {body.decision}")
        item.status = ActionStatus.dismissed if body.decision == "skip" else ActionStatus.resolved
        item.resolved_at = utcnow()
        return {"job_state": job.state}


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
