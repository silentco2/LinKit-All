"""Score stage: the AI tiers the best locally-ranked jobs, in batches (CLAUDE.md §5.3, §5.6).

ranked -> scored -> queued_apply (high) | awaiting_review (mid) | below_threshold (low).
Jobs outside the top `ai_max_jobs` go straight to below_threshold (tier low).
With `matching.auto_apply_low` the low tier is queued for apply instead, and existing
below_threshold jobs are re-queued on the next score run.
"""

from typing import Any, Literal, Self

from loguru import logger
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Job, JobState, Profile, Tier, utcnow
from linkit_all.core.runs import pause_run
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.matching.facts import JobFacts, checked, fill, missing
from linkit_all.matching.rank import LOW_OPT_IN, cv_text
from linkit_all.matching.rules import expectation_of, rule_violation
from linkit_all.matching.trash import not_trash
from linkit_all.matching.trust_stage import add_ai_flag
from linkit_all.providers.base import LLMProvider, UsageLimitError, render

CV_CHARS = 6000
MAX_TRUST_FLAGS = 3
JD_CHARS = 1500  # per job; enough for the role, stack and requirements


MAX_REQUIREMENTS = 8
SHORT_JD = 400  # a description under this many characters cannot carry a confident score
Confidence = Literal["low", "medium", "high"]


def _one_of(*known: str) -> Any:
    """A before-validator that reads an unknown value as the field's default (the last one
    named) instead of failing the whole batch."""
    return lambda v: v if v in known else known[-1]


class Requirement(BaseModel):
    """One thing the posting asks for, and whether the CV shows it."""

    text: str
    importance: Literal["critical", "high", "preferred", "meaningful"] = "meaningful"
    # stated: the posting says it; structural: the title or level implies it; inferred: a guess.
    basis: Literal["stated", "structural", "inferred"] = "inferred"
    met: Literal["yes", "no", "partial"] = "partial"

    _importance = field_validator("importance", mode="before")(
        _one_of("critical", "high", "preferred", "meaningful")
    )
    _basis = field_validator("basis", mode="before")(_one_of("stated", "structural", "inferred"))
    _met = field_validator("met", mode="before")(_one_of("yes", "no", "partial"))

    @model_validator(mode="after")
    def _guess_is_never_decisive(self) -> Self:
        if self.basis == "inferred" and self.importance in ("critical", "high"):
            self.importance = "meaningful"
        return self


class JobScore(BaseModel):
    job_id: int
    score: int = Field(ge=1, le=10)
    reasons: list[str] = []
    missing_skills: list[str] = []
    red_flags: list[str] = []
    # Optional, so cached answers from before these fields still validate.
    requirements: list[Requirement] = []
    cv_evidence: Literal["missing", "found"] = "found"

    _cv_evidence = field_validator("cv_evidence", mode="before")(_one_of("missing", "found"))

    @field_validator("requirements")
    @classmethod
    def _cap_requirements(cls, v: list[Requirement]) -> list[Requirement]:
        return v[:MAX_REQUIREMENTS]

    # Legitimacy is separate from fit. Optional so old cached answers and models that omit it
    # still validate; an unknown `legit` value is read as "ok" rather than failing the batch.
    legit: Literal["ok", "suspicious", "scam"] = "ok"
    trust_flags: list[str] = []
    facts: JobFacts | None = None  # blanks the posting fills; kept only when checked (facts.py)

    @field_validator("legit", mode="before")
    @classmethod
    def _known_legit(cls, v: Any) -> Any:
        return v if v in ("ok", "suspicious", "scam") else "ok"

    @field_validator("trust_flags")
    @classmethod
    def _cap_trust_flags(cls, v: list[str]) -> list[str]:
        return v[:MAX_TRUST_FLAGS]


class ScoreBatch(BaseModel):
    results: list[JobScore]


def confidence_of(description: str, r: JobScore) -> Confidence:
    """How far to trust a score. Shown beside it; never changes the tier.

    low: too little to judge from (a short or cut-off description, or the AI found no CV
    evidence). high: the AI read the whole description and every requirement it listed comes
    from the posting or the role itself. medium: everything else."""
    text = description.strip()
    if len(text) < SHORT_JD or text.endswith(("…", "...")) or r.cv_evidence == "missing":
        return "low"
    grounded = bool(r.requirements) and all(q.basis != "inferred" for q in r.requirements)
    return "high" if grounded and len(description) <= JD_CHARS else "medium"


def tier_for(score: int, cfg: SearchConfig) -> Tier:
    if score >= cfg.matching.tier_high:
        return Tier.high
    return Tier.mid if score >= cfg.matching.tier_mid else Tier.low


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
            old_lows = list(
                s.scalars(
                    select(Job)
                    .filter_by(state=JobState.below_threshold)
                    .where(not_trash(), Job.data["fact_rule"].as_string().is_(None))
                )
            )
            for job in old_lows:
                transition(s, job, JobState.queued_apply, LOW_OPT_IN, code="low_opt_in")
            counts["requeued_low"] = len(old_lows)
        ranked = list(s.scalars(select(Job).filter_by(state=JobState.ranked)))
        ranked.sort(key=lambda j: -j.data.get("rank", 0))
        top, rest = ranked[: cfg.matching.ai_max_jobs], ranked[cfg.matching.ai_max_jobs :]
        for job in rest:  # the free prefilter decided: low tier, no AI spent
            job.tier = Tier.low
            transition(
                s, job, JobState.below_threshold, "outside the top ranked jobs", code="below_top"
            )
            if opt_in:
                transition(s, job, JobState.queued_apply, LOW_OPT_IN, code="low_opt_in")
        counts["low"] += len(rest)
        size = min(cfg.matching.batch_size, provider.max_batch or cfg.matching.batch_size)
        batches = [
            [{"id": j.id, "title": j.title, "company": j.company, "location": j.location,
              "remote": j.data.get("remote"), "description": j.description[:JD_CHARS],
              "missing": [] if j.data.get("manual") else missing(j)}
             for j in top[i : i + size]]
            for i in range(0, len(top), size)
        ]  # fmt: skip
    f = cfg.filters
    prefs = {"titles": ", ".join(f.title_include), "locations": ", ".join(f.locations),
             "work_modes": ", ".join(f.work_modes),
             "seniority": ", ".join(f.seniority)}  # fmt: skip
    cv = cv_text(profile)[:CV_CHARS]
    expect = expectation_of(profile.answers, cfg)

    for n, batch in enumerate(batches, 1):
        try:
            result = await provider.complete(
                render("score.j2", cv=cv, prefs=prefs, jobs=batch), ScoreBatch
            )
        except UsageLimitError as e:  # pause cleanly; ranked jobs are scored on resume
            logger.bind(code=e.code, params={"batches": n - 1}).warning(
                "AI stopped after {} batches: {}", n - 1, e
            )
            if run_id is not None:
                pause_run(
                    db, run_id, e.message, e.code,
                    {"provider": e.provider, "until": e.until},
                )  # fmt: skip
            counts["not_scored"] += sum(len(b) for b in batches[n - 1 :])
            break
        scores = {r.job_id: r for r in result.results}
        with db.begin() as s:
            for item in batch:
                job = s.get_one(Job, item["id"])
                if (r := scores.get(job.id)) is None:
                    counts["not_scored"] += 1  # stays ranked; the next score run retries it
                    continue
                ai: dict[str, Any] = r.model_dump(exclude={"job_id", "facts"})
                broken = _check_facts(job, r.facts, cfg, expect) if item["missing"] else None
                job.score, job.tier, job.data = (
                    r.score,
                    tier_for(r.score, cfg),
                    {**job.data, "ai": ai, "confidence": confidence_of(job.description, r)},
                )
                if add_ai_flag(job, r.legit) and job.tier == Tier.high:
                    job.tier = (
                        Tier.mid
                    )  # the AI calls it a scam: a person decides, never auto-apply
                transition(
                    s, job, JobState.scored, f"AI score {r.score}",
                    code="ai_scored", params={"score": r.score},
                )  # fmt: skip
                if broken:  # a checked fact breaks a hard rule: low tier, never applied by itself
                    job.tier = Tier.low
                    transition(s, job, JobState.below_threshold, broken, code="fact_rule")
                elif job.tier == Tier.low and opt_in:
                    transition(s, job, JobState.queued_apply, LOW_OPT_IN, code="low_opt_in")
                else:
                    transition(
                        s, job, _NEXT[job.tier], f"tier {job.tier}",
                        code="tier_set", params={"tier": str(job.tier)},
                    )  # fmt: skip
                counts[job.tier] += 1
        logger.bind(code="score_batch", params={"n": n, "total": len(batches)}).info(
            "scored batch {}/{}", n, len(batches)
        )
    return counts


def _check_facts(
    job: Job, facts: JobFacts | None, cfg: SearchConfig, expect: tuple[float, str] | None
) -> str | None:
    """Fill the job's blanks with the checked facts; the hard rule they now break, if any
    (kept in data["fact_rule"], so the low opt-in never queues it)."""
    if not (kept := checked(job, facts)):
        return None
    fill(job, kept)
    if reason := rule_violation(job, cfg, utcnow(), expect):
        job.data = {**job.data, "fact_rule": reason}
    return reason
