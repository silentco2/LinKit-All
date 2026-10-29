"""Answer bank lookups, AI drafts (non-sensitive only) and cover letters."""

import re
from pathlib import Path
from typing import Any

import numpy as np
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.answers import (
    CHOICE_KINDS,
    Context,
    Missing,
    Question,
    Resolution,
    is_cover_letter,
    pick_canonical,
    pick_option,
    resolve_static,
    valid_for,
)  # fmt: skip
from linkit_all.core.models import AnswerEntry
from linkit_all.matching.rank import Embed
from linkit_all.providers.base import LLMProvider, UsageLimitError, render

MATCH = 0.93  # paraphrase similarity needed to reuse a saved answer
MATCH_SENSITIVE = 0.97  # sensitive questions: near-identical wording, the user's own answers only


class AnswerBank:
    def __init__(self, db: sessionmaker[Session], embed: Embed | None = None) -> None:
        self.db, self.embed = db, embed
        self._entries: list[AnswerEntry] | None = None
        self._vecs: np.ndarray[Any, np.dtype[np.float64]] | None = None

    def _load(self) -> list[AnswerEntry]:
        if self.embed is None:
            raise RuntimeError("AnswerBank needs an embedder for lookups")
        if self._entries is None:
            with self.db() as s:
                self._entries = list(s.scalars(select(AnswerEntry)))
            self._vecs = self.embed([e.question for e in self._entries]) if self._entries else None
        return self._entries

    def lookup(self, q: Question, sensitive: bool = False) -> Any:
        entries = self._load()
        if not entries or self._vecs is None:
            return None
        assert self.embed is not None  # _load checked  # noqa: S101
        sims = self._vecs @ self.embed([q.label])[0]
        for i in np.argsort(-sims):
            if sims[i] < (MATCH_SENSITIVE if sensitive else MATCH):
                break
            entry = entries[i]
            if sensitive and entry.source != "user":
                continue
            if (value := _fit(q, entry.answer)) is not None:
                with self.db.begin() as s:
                    s.get_one(AnswerEntry, entry.id).uses += 1
                return value
        return None

    def save(
        self,
        question: str,
        answer: Any,
        source: str,
        sensitive: bool = False,
        session: Session | None = None,
    ) -> None:
        """Save in `session` when given (the caller commits), else in a transaction of its own."""
        key = " ".join(question.lower().split())
        if session is None:
            with self.db.begin() as s:
                self.save(question, answer, source, sensitive, s)
            return
        existing = next(
            (
                e
                for e in session.scalars(select(AnswerEntry))
                if " ".join(e.question.lower().split()) == key
            ),
            None,
        )
        if existing is None:
            session.add(
                AnswerEntry(question=question, answer=answer, source=source, sensitive=sensitive)
            )
        elif source == "user" or existing.source == "ai":  # never overwrite the user's words
            existing.answer, existing.source = answer, source
        self._entries = None


def _fit(q: Question, answer: Any) -> Any:
    """A saved answer reshaped for this form's options, or None if it does not fit."""
    if valid_for(q, answer):
        return answer
    if q.kind in CHOICE_KINDS and isinstance(answer, str):
        return pick_option(q.options, answer) or pick_canonical(q.options, answer.strip().lower())
    if q.kind == "checkbox" and isinstance(answer, str):
        return answer.strip().lower() in ("yes", "true")
    return None


class Draft(BaseModel):
    key: str
    known: bool  # False when the CV/profile does not support an answer
    answer: str | list[str] | bool | None = None


class Drafts(BaseModel):
    answers: list[Draft]


class CoverLetter(BaseModel):
    text: str


def _job_brief(job: dict[str, str]) -> dict[str, str]:
    return {**job, "description": job.get("description", "")[:4000]}


async def ai_drafts(
    provider: LLMProvider, questions: list[Question], cv: str, profile: str, job: dict[str, str]
) -> dict[str, Any]:
    if not questions:
        return {}
    prompt = render(
        "answer.j2", questions=questions, cv=cv[:6000], profile=profile, job=_job_brief(job)
    )
    result = await provider.complete(prompt, Drafts)
    by_key = {q.key: q for q in questions}
    out = {}
    for d in result.answers:
        q = by_key.get(d.key)
        if q is not None and d.known and (value := _fit(q, d.answer)) is not None:
            out[q.key] = value
    return out


async def write_cover_letter(
    provider: LLMProvider, cv: str, profile: str, job: dict[str, str], out_dir: Path
) -> tuple[str, Path]:
    """Letter text and a simple PDF of it (for upload fields)."""
    import pymupdf

    prompt = render("cover_letter.j2", cv=cv[:6000], profile=profile, job=_job_brief(job))
    text = (await provider.complete(prompt, CoverLetter)).text.strip()
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / "cover_letter.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(72, 72, page.rect.width - 72, page.rect.height - 72), text,
                        fontsize=11, fontname="helv")  # fmt: skip
    doc.save(str(pdf))
    return text, pdf


async def answer_questions(
    questions: list[Question],
    ctx: Context,
    bank: AnswerBank,
    provider: LLMProvider | None,
    cv: str,
    profile: str,
    job: dict[str, str],
    out_dir: Path,
) -> Resolution:
    """Full resolution; anything required and still unanswered ends in `missing`."""
    letter = ""
    if provider is not None and any(is_cover_letter(q) for q in questions):
        letter, pdf = await write_cover_letter(provider, cv, profile, job, out_dir)
        ctx.cover_letter_path = str(pdf)

    r = resolve_static(questions, ctx)
    still_missing = []
    for m in r.missing:  # the user may have answered this exact question before
        if m.sensitive and (value := bank.lookup(m.question, sensitive=True)) is not None:
            r.answers[m.question.key], r.sources[m.question.key] = value, "bank"
        else:
            still_missing.append(m)
    r.missing = still_missing

    for_ai = []
    for q in r.pending:
        if is_cover_letter(q) and q.kind == "textarea" and letter:
            r.answers[q.key], r.sources[q.key] = letter, "ai"
        elif (value := bank.lookup(q)) is not None:
            r.answers[q.key], r.sources[q.key] = value, "bank"
        else:
            for_ai.append(q)
    if provider is not None and for_ai:
        try:
            drafted = await ai_drafts(provider, for_ai, cv, profile, job)
        except UsageLimitError:
            raise  # pause the run; the job is retried later instead of parked
        except Exception as e:  # a bad AI answer must not lose the application
            logger.warning("AI drafts failed: {}", e)
            drafted = {}
        for q in for_ai:
            if q.key in drafted:
                r.answers[q.key], r.sources[q.key] = drafted[q.key], "ai"
                bank.save(q.label, drafted[q.key], "ai")
            elif q.required:
                r.missing.append(Missing(q, "not answerable from your CV or profile"))
    else:
        r.missing += [Missing(q, "no saved answer") for q in for_ai if q.required]
    r.pending = []
    return r


_SPACES = re.compile(r"\s+")


def profile_summary(ctx: Context) -> str:
    """Non-sensitive profile facts the AI may use (no salary, visa or demographics)."""
    a = ctx.answers
    facts = {
        "Name": ctx.full_name,
        "Location": a.city or ctx.location,
        "Current company": a.current_company,
        "Current title": a.current_title,
        "Years of experience": a.years_experience,
        "Notice period": a.notice_period,
        "LinkedIn": a.linkedin,
        "GitHub": a.github,
        "Portfolio": a.portfolio,
        "Willing to relocate": a.willing_to_relocate,
    }
    return "\n".join(f"{k}: {v}" for k, v in facts.items() if v not in (None, ""))
