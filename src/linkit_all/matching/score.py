"""Score stage: the AI tiers the best locally-ranked jobs, in batches (CLAUDE.md §5.3, §5.6).

ranked -> scored -> queued_apply (high) | awaiting_review (mid) | below_threshold (low).
Jobs outside the top `ai_max_jobs` go straight to below_threshold (tier low).
With `matching.auto_apply_low` the low tier is queued for apply instead, and existing
below_threshold jobs are re-queued on the next score run.
"""

from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Job, JobState, Profile, Run, RunStatus, Tier
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.matching.rank import cv_text
from linkit_all.providers.base import LLMProvider, UsageLimitError, render

CV_CHARS = 6000
MAX_TRUST_FLAGS = 3
JD_CHARS = 1500  # per job; enough for the role, stack and requirements


class JobScore(BaseModel):
    job_id: int
    score: int = Field(ge=1, le=10)
    reasons: list[str] = []
    missing_skills: list[str] = []
    red_flags: list[str] = []
    # Legitimacy is separate from fit. Optional so old cached answers and models that omit it
    # still validate; an unknown `legit` value fails validation and takes the retry path.
    legit: Literal["ok", "suspicious", "scam"] = "ok"
    trust_flags: list[str] = []

    @field_validator("trust_flags")
    @classmethod
    def _cap_trust_flags(cls, v: list[str]) -> list[str]:
        return v[:MAX_TRUST_FLAGS]


class ScoreBatch(BaseModel):
    results: list[JobScore]


def tier_for(score: int, cfg: SearchConfig) -> Tier:
    if score >= cfg.matching.tier_high:
        return Tier.high
    return Tier.mid if score >= cfg.matching.tier_mid else Tier.low


LOW_OPT_IN = "queued by the low-tier auto-apply opt-in"
_NEXT = {Tier.high: JobState.queued_apply, Tier.mid: JobState.awaiting_review,
         Tier.low: JobState.below_threshold}  # fmt: skip


async def score_jobs(
    db: sessionmaker[Session], cfg: SearchConfig, provider: LLMProvider, run_id: int | None = None
) -> dict[str, int]:
    counts = {"high": 0, "mid": 0, "low": 0, "not_scored": 0}
    opt_in = cfg.matching.auto_apply_low
    with db.begin() as s:
        profile = s.get(Profile, 1)
        if profile is None:
            raise ValueError("No profile yet: run `linkit profile import profile.json`")
        if opt_in:  # opt-in turned on later: pick up earlier lows too
            old_lows = list(s.scalars(select(Job).filter_by(state=JobState.below_threshold)))
            for job in old_lows:
                transition(s, job, JobState.queued_apply, LOW_OPT_IN)
            counts["requeued_low"] = len(old_lows)
        ranked = list(s.scalars(select(Job).filter_by(state=JobState.ranked)))
        ranked.sort(key=lambda j: -j.data.get("rank", 0))
        top, rest = ranked[: cfg.matching.ai_max_jobs], ranked[cfg.matching.ai_max_jobs :]
        for job in rest:  # the free prefilter decided: low tier, no AI spent
            job.tier = Tier.low
            transition(s, job, JobState.below_threshold, "outside the top ranked jobs")
            if opt_in:
                transition(s, job, JobState.queued_apply, LOW_OPT_IN)
        counts["low"] += len(rest)
        batches = [
            [{"id": j.id, "title": j.title, "company": j.company, "location": j.location,
              "remote": j.data.get("remote"), "description": j.description[:JD_CHARS]}
             for j in top[i : i + cfg.matching.batch_size]]
            for i in range(0, len(top), cfg.matching.batch_size)
        ]  # fmt: skip
    f = cfg.filters
    prefs = {"titles": ", ".join(f.title_include), "locations": ", ".join(f.locations),
             "work_modes": ", ".join(f.work_modes),
             "seniority": ", ".join(f.seniority)}  # fmt: skip
    cv = cv_text(profile)[:CV_CHARS]

    for n, batch in enumerate(batches, 1):
        try:
            result = await provider.complete(
                render("score.j2", cv=cv, prefs=prefs, jobs=batch), ScoreBatch
            )
        except UsageLimitError as e:  # pause cleanly; ranked jobs are scored on resume
            logger.warning("AI usage limit reached after {} batches: {}", n - 1, e)
            if run_id is not None:
                with db.begin() as s:
                    run = s.get_one(Run, run_id)
                    run.status, run.pause_reason = RunStatus.paused, f"AI usage limit: {e}"
            counts["not_scored"] += sum(len(b) for b in batches[n - 1 :])
            break
        scores = {r.job_id: r for r in result.results}
        with db.begin() as s:
            for item in batch:
                job = s.get_one(Job, item["id"])
                if (r := scores.get(job.id)) is None:
                    counts["not_scored"] += 1  # stays ranked; the next score run retries it
                    continue
                ai: dict[str, Any] = r.model_dump(exclude={"job_id"})
                job.score, job.tier, job.data = (
                    r.score,
                    tier_for(r.score, cfg),
                    {**job.data, "ai": ai},
                )
                transition(s, job, JobState.scored, f"AI score {r.score}")
                if job.tier == Tier.low and opt_in:
                    transition(s, job, JobState.queued_apply, LOW_OPT_IN)
                else:
                    transition(s, job, _NEXT[job.tier], f"tier {job.tier}")
                counts[job.tier] += 1
        logger.info("scored batch {}/{}", n, len(batches))
    return counts
