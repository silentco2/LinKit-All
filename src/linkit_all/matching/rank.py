"""Rank stage: hard rules, then free local ranking (embeddings + skill overlap). No AI."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Job, JobState, Profile, Tier, utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.matching.rules import rule_violation
from linkit_all.matching.trust_stage import allowed, score_jobs_trust, top_codes
from linkit_all.sources.text import norm_company
from linkit_all.tailor.pipeline import cv_segments

Vectors = np.ndarray[Any, np.dtype[np.float64]]
Embed = Callable[[list[str]], Vectors]  # texts -> L2-normalized rows

LOW_OPT_IN = "queued by the low-tier auto-apply opt-in"
CHUNK_WORDS = 80  # the multilingual MiniLM reads 128 tokens; Arabic needs ~1.5 per word
MAX_WORDS = 640  # a JD's opening says what the job is; the rest is boilerplate
# A company with a job in any of these states already has "its" application.
TAKEN = (JobState.ranked, JobState.scored, JobState.awaiting_review, JobState.queued_apply,
         JobState.tailored, JobState.applying, JobState.needs_user, JobState.applied)  # fmt: skip


class Embedder:
    """fastembed model; long texts are embedded as chunks and mean-pooled."""

    def __init__(self, model: str, cache_dir: Path) -> None:
        from fastembed import TextEmbedding  # loads onnxruntime; only when ranking

        self._model = TextEmbedding(model_name=model, cache_dir=str(cache_dir))

    def __call__(self, texts: list[str]) -> Vectors:
        chunks: list[str] = []
        owner: list[int] = []
        for i, text in enumerate(texts):
            words = text.split()[:MAX_WORDS] or [""]
            for k in range(0, len(words), CHUNK_WORDS):
                chunks.append(" ".join(words[k : k + CHUNK_WORDS]))
                owner.append(i)
        vecs = np.array(list(self._model.embed(chunks, batch_size=64)), dtype=np.float64)
        pooled = np.zeros((len(texts), vecs.shape[1]))
        np.add.at(pooled, owner, vecs)
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        return pooled / np.clip(norms, 1e-9, None)


def cv_text(profile: Profile) -> str:
    return "\n".join(s.text for s in cv_segments(Path(profile.cv_path)))


def skill_overlap(skills: list[str], text: str) -> float:
    if not skills:
        return 0.0
    low = text.lower()
    hits = sum(1 for s in skills if re.search(rf"(?<!\w){re.escape(s.lower())}(?!\w)", low))
    return hits / len(skills)


def _trust_filtered(job: Job, cfg: SearchConfig) -> bool:
    """Would the stored trust scores still filter this job out under today's settings?"""
    t, trust = cfg.trust, job.data.get("trust")
    if not t.enabled or not trust:
        return False
    if job.data.get("trust_filter") == "scam":
        return trust["scam"]["score"] >= t.scam_threshold and norm_company(
            job.company
        ) not in allowed(cfg)
    return t.filter_ghost and trust["ghost"]["score"] >= t.ghost_threshold


def _apply_trust(
    s: Session, keep: list[Job], cfg: SearchConfig, counts: dict[str, int]
) -> list[Job]:
    """Score scam and ghost risk; filter scams, filter or demote ghosts. Returns the survivors."""
    t, allow = cfg.trust, allowed(cfg)
    scores = score_jobs_trust(s, keep)
    survivors: list[Job] = []
    for job in keep:
        trust = scores[job.id]
        job.data = {**job.data, "trust": trust}
        scam, ghost = trust["scam"]["score"], trust["ghost"]["score"]
        if scam >= t.scam_threshold and norm_company(job.company) not in allow:
            job.data = {**job.data, "trust_filter": "scam"}
            transition(
                s, job, JobState.filtered_out,
                f"looks like a scam (score {scam}): {top_codes(trust, 'scam')}",
                code="scam_suspected", params={"score": scam},
            )  # fmt: skip
            counts["filtered_out"] += 1
            counts["scam_filtered"] = counts.get("scam_filtered", 0) + 1
        elif ghost >= t.ghost_threshold and t.filter_ghost:
            job.data = {**job.data, "trust_filter": "ghost"}
            transition(
                s, job, JobState.filtered_out,
                f"looks like a ghost job (score {ghost}): {top_codes(trust, 'ghost')}",
                code="ghost_suspected", params={"score": ghost},
            )  # fmt: skip
            counts["filtered_out"] += 1
            counts["ghost_filtered"] = counts.get("ghost_filtered", 0) + 1
        elif ghost >= t.ghost_threshold:
            # Low tier without embeddings or AI; the low-tier opt-in decides whether it is applied.
            job.data = {**job.data, "trust": {**trust, "ghost_demoted": True}}
            job.tier = Tier.low
            transition(s, job, JobState.ranked, "local rank skipped: likely a ghost job")
            transition(
                s, job, JobState.below_threshold,
                f"likely a ghost job (score {ghost}): {top_codes(trust, 'ghost')}",
                code="ghost_likely", params={"score": ghost},
            )  # fmt: skip
            if cfg.matching.auto_apply_low:
                transition(s, job, JobState.queued_apply, LOW_OPT_IN)
            counts["ghost_demoted"] = counts.get("ghost_demoted", 0) + 1
        else:
            survivors.append(job)
    return survivors


def rank_jobs(db: sessionmaker[Session], cfg: SearchConfig, embed: Embed) -> dict[str, int]:
    """enriched -> filtered_out | ranked (data["rank"] in 0..1), one best job per company."""
    with db() as s:
        profile = s.get(Profile, 1)
        if profile is None:
            raise ValueError("No profile yet: run `linkit profile import profile.json`")
        taken = {
            norm_company(c) for c in s.scalars(select(Job.company).where(Job.state.in_(TAKEN)))
        }
    cv = cv_text(profile)
    counts = {"ranked": 0, "filtered_out": 0}
    now = utcnow()
    with db.begin() as s:
        # Jobs a hard rule dropped earlier get another look when they pass today's filters
        # (filters changed, or a rule was fixed). Company-rule drops stay put.
        for job in s.scalars(select(Job).filter_by(state=JobState.filtered_out)):
            if job.data.get("company_rule") or rule_violation(job, cfg, now) is not None:
                continue
            if job.data.get("trust_filter") and _trust_filtered(job, cfg):
                continue  # still a scam / ghost under today's trust settings
            job.data = {k: v for k, v in job.data.items() if k != "trust_filter"}
            transition(s, job, JobState.enriched, "passes your filters now: checked again")
            counts["rechecked"] = counts.get("rechecked", 0) + 1
        jobs = list(s.scalars(select(Job).filter_by(state=JobState.enriched)))
        keep = []
        for job in jobs:
            if reason := rule_violation(job, cfg, now):
                transition(s, job, JobState.filtered_out, reason)
                counts["filtered_out"] += 1
            else:
                keep.append(job)
        if cfg.trust.enabled and keep:
            keep = _apply_trust(s, keep, cfg, counts)
        if not keep:
            return counts
        vecs = embed([cv] + [f"{j.title}\n{j.description}" for j in keep])
        cosine = vecs[1:] @ vecs[0]
        for job, cos in zip(keep, cosine, strict=True):
            overlap = skill_overlap(profile.skills, f"{job.title} {job.description}")
            score = 0.8 * float(cos) + 0.2 * overlap if profile.skills else float(cos)
            job.data = {**job.data, "rank": round(score, 4), "skill_overlap": round(overlap, 3)}

        best: dict[str, Job] = {}
        for job in sorted(keep, key=lambda j: -j.data["rank"]):
            company = norm_company(job.company)
            if cfg.filters.one_per_company and (company in taken or company in best):
                why = (
                    "already in your pipeline for this company"
                    if company in taken
                    else ("a better match at this company ranked higher")
                )
                job.data = {**job.data, "company_rule": True}  # not re-checked by the loop above
                transition(s, job, JobState.filtered_out, why)
            else:
                best[company] = job
                transition(s, job, JobState.ranked, f"local rank {job.data['rank']:.3f}")
                counts["ranked"] += 1
                continue
            counts["filtered_out"] += 1
    return counts
