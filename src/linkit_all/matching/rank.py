"""Rank stage: hard rules, then free local ranking (embeddings + skill overlap). No AI."""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from docx import Document
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Job, JobState, Profile, utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition
from linkit_all.matching.rules import rule_violation
from linkit_all.sources.text import norm_company
from linkit_all.tailor.docx.segments import load_segments

Vectors = np.ndarray[Any, np.dtype[np.float64]]
Embed = Callable[[list[str]], Vectors]  # texts -> L2-normalized rows

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
    return "\n".join(s.text for s in load_segments(Document(profile.cv_path)) if s.text.strip())


def skill_overlap(skills: list[str], text: str) -> float:
    if not skills:
        return 0.0
    low = text.lower()
    hits = sum(1 for s in skills if re.search(rf"(?<!\w){re.escape(s.lower())}(?!\w)", low))
    return hits / len(skills)


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
        jobs = list(s.scalars(select(Job).filter_by(state=JobState.enriched)))
        keep = []
        for job in jobs:
            if reason := rule_violation(job, cfg, now):
                transition(s, job, JobState.filtered_out, reason)
                counts["filtered_out"] += 1
            else:
                keep.append(job)
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
            if cfg.filters.one_per_company and company in taken:
                transition(
                    s, job, JobState.filtered_out, "already in your pipeline for this company"
                )
            elif cfg.filters.one_per_company and company in best:
                transition(
                    s, job, JobState.filtered_out, "a better match at this company ranked higher"
                )
            else:
                best[company] = job
                transition(s, job, JobState.ranked, f"local rank {job.data['rank']:.3f}")
                counts["ranked"] += 1
                continue
            counts["filtered_out"] += 1
    return counts
