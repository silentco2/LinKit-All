"""One follow-up email for an application sent by email that got no reply. Live mode only, and
only when "submit without asking" is on (the maintainer's choice: follow-ups go out by
themselves); otherwise the job's history says one is due. Never twice for a job, never after
any reply, counted in the daily email cap. Dry run writes an .eml only. The body is the
model's (CV only, English); greeting and signature are ours. Logic adapted from career-ops (MIT)."""

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.answers import ApplicationAnswers
from linkit_all.apply.email_apply import greeting, signature
from linkit_all.apply.email_send import (
    OutgoingEmail,
    SmtpError,
    build_message,
    save_eml,
    send,
    valid_address,
)
from linkit_all.apply.prose import clean
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings
from linkit_all.core.models import Job, JobEvent, JobState, Outcome, Profile, utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.matching.rank import cv_text
from linkit_all.providers.base import LLMProvider, render
from linkit_all.tailor.patches import has_arabic

MAX_WORDS = 100


class FollowUp(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def _body(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v.split()) > MAX_WORDS:
            raise ValueError(f"body must be 1 to {MAX_WORDS} words")
        return v


def _when(stamp: str) -> datetime:
    d = datetime.fromisoformat(stamp)
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def due(s: Session, days: int, now: datetime | None = None) -> list[Job]:
    """Applied by email at least `days` ago, no reply recorded, no follow-up yet."""
    now = now or utcnow()
    now = now if now.tzinfo else now.replace(tzinfo=UTC)
    out = []
    for job in s.scalars(select(Job).where(Job.state == JobState.applied)):
        sent = job.data.get("email_sent")
        if not isinstance(sent, dict) or not sent.get("sent_at") or job.data.get("followup_sent"):
            continue
        if job.outcome not in (None, Outcome.no_reply):
            continue
        if _when(sent["sent_at"]) <= now - timedelta(days=days):
            out.append(job)
    return out


def _event(
    s: Session, job: Job, message: str, code: str, artifacts: list[str], **params: Any
) -> None:
    s.add(JobEvent(job=job, from_state=job.state, to_state=job.state, message=message, code=code,
                   params=params, artifacts=artifacts))  # fmt: skip


async def send_followups(
    db: sessionmaker[Session],
    settings: Settings,
    cfg: SearchConfig,
    provider: LLMProvider,
    vault: Vault | None,
    sent_today: int,
) -> dict[str, int]:
    """Counts only. `sent_today`: application and follow-up emails already sent today."""
    apply_cfg, counts = cfg.apply, {"sent": 0, "previewed": 0, "due": 0}
    with db() as s:
        profile = s.get(Profile, 1)
        jobs = [
            (j.id, j.title, j.company, j.description, dict(j.data))
            for j in due(s, apply_cfg.followup_days)
        ]
    if profile is None or not jobs:
        return counts
    answers = ApplicationAnswers.model_validate(profile.answers)
    sender = (cfg.email.imap_user or profile.email).strip()
    for job_id, title, company, description, data in jobs:
        auto = apply_cfg.live and apply_cfg.submit_without_asking
        if apply_cfg.live and not auto:
            if not data.get("followup_due_noted"):
                with db.begin() as s:
                    job = s.get_one(Job, job_id)
                    job.data = {**job.data, "followup_due_noted": True}
                    _event(s, job, "a follow-up email is due: no reply yet", "followup_due", [])
                counts["due"] += 1
            continue
        if apply_cfg.live and sent_today >= apply_cfg.email_daily_cap:
            break
        if not apply_cfg.live and data.get("followup_preview_at"):
            continue
        first = data["email_sent"]
        sent_on = _when(first["sent_at"]).strftime("%d %B %Y")
        prompt = render(
            "followup_email.j2",
            days=apply_cfg.followup_days,
            sent_on=sent_on,
            job={"title": title, "company": company, "description": description[:3000]},
            cv=cv_text(profile)[:5000],
        )
        try:
            reply = await provider.complete(prompt, FollowUp)
        except Exception as e:
            logger.warning("job {}: follow-up not written ({})", job_id, type(e).__name__)
            continue
        if has_arabic(reply.body):  # all AI-written prose is English (CLAUDE.md §5.5)
            continue
        draft = data.get("email_draft") or {}
        subject = f"Re: {draft.get('subject') or title}"
        sign = signature(profile.full_name, profile.phone, answers.linkedin)
        body = f"{greeting(None)}\n\n{clean(reply.body)}\n\n{sign}"
        msg = build_message(
            profile.full_name,
            sender,
            OutgoingEmail(
                first["to"],
                subject,
                body,
                reply_to=profile.email
                if valid_address(profile.email) and profile.email.strip().lower() != sender.lower()
                else None,
            ),
        )
        if first.get("message_id"):  # thread it under the application
            msg["In-Reply-To"] = msg["References"] = first["message_id"]
        out_dir = settings.data_dir / "applications" / f"job_{job_id}"
        if not apply_cfg.live:
            eml = str(save_eml(msg, out_dir / "followup.eml"))
            with db.begin() as s:
                job = s.get_one(Job, job_id)
                job.data = {**job.data, "followup_preview_at": utcnow().isoformat()}
                _event(s, job, f"dry run: follow-up to {first['to']} prepared, not sent",
                       "followup_preview", [eml], to=first["to"])  # fmt: skip
            counts["previewed"] += 1
            continue
        if vault is None or not vault.unlocked():
            break
        try:
            message_id = await asyncio.to_thread(send, cfg.email, vault, profile.email, msg)
        except SmtpError as e:
            logger.warning("job {}: follow-up not sent ({})", job_id, type(e).__name__)
            continue
        eml = str(save_eml(msg, Path(out_dir) / "followup_sent.eml"))
        with db.begin() as s:
            job = s.get_one(Job, job_id)
            job.data = {
                **job.data,
                "followup_sent": {"message_id": message_id, "sent_at": utcnow().isoformat()},
            }
            _event(s, job, f"follow-up emailed to {first['to']}", "followup_sent", [eml],
                   to=first["to"])  # fmt: skip
        sent_today += 1
        counts["sent"] += 1
    return counts
