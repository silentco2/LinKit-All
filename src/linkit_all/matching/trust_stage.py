"""Glue between the offline trust scorers and the pipeline (rank and score stages, API)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from linkit_all.core.models import Job, utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.matching.trust import Verdict
from linkit_all.matching.trust.ghost import GhostHistory, ghost_histories, score_ghost
from linkit_all.matching.trust.scam import HIGH_FROM, MEDIUM_FROM, SalaryLike, score_scam
from linkit_all.sources.text import norm_company

AI_FLAG_SCAM, AI_FLAG_SUSPICIOUS = 30, 15
TOP_SIGNALS = 3


def _verdict_dict(v: Verdict) -> dict[str, Any]:
    return {
        "score": v.score,
        "band": v.band,
        "signals": [
            {"code": s.code, "weight": s.weight, "evidence": s.evidence} for s in v.signals
        ],
    }


def _salary(job: Job) -> SalaryLike:
    d = job.data
    return {"min": d.get("salary_min"), "max": d.get("salary_max"),
            "currency": d.get("salary_currency"), "interval": d.get("salary_interval")}  # fmt: skip


def allowed(cfg: SearchConfig) -> set[str]:
    """Normalized names of companies the user marked "not a scam"."""
    return {norm_company(c) for c in cfg.trust.allow_companies}


def top_codes(trust: dict[str, Any], kind: str, n: int = TOP_SIGNALS) -> str:
    sigs = sorted(trust[kind]["signals"], key=lambda s: -s["weight"])
    return ", ".join(s["code"] for s in sigs[:n] if s["weight"] > 0) or "no single signal"


def score_jobs_trust(
    session: Session, jobs: Sequence[Job], now: datetime | None = None
) -> dict[int, dict[str, Any]]:
    """Both verdicts per job id, as the dicts stored in `job.data["trust"]`."""
    now = now or utcnow()
    hist: dict[int, GhostHistory] = ghost_histories(session, jobs)
    out: dict[int, dict[str, Any]] = {}
    for job in jobs:
        scam = score_scam(job.title, job.company, job.description,
                          job.data.get("apply_url"), _salary(job),
                          job.data.get("company_url"))  # fmt: skip
        ghost = score_ghost(job.title, job.company, job.description, job.posted_at,
                            _salary(job), hist[job.id], now)  # fmt: skip
        out[job.id] = {"scam": _verdict_dict(scam), "ghost": _verdict_dict(ghost),
                       "checked_at": now.isoformat()}  # fmt: skip
    return out


def add_ai_flag(job: Job, legit: str) -> bool:
    """The AI's `legit` verdict adds a scam signal; it never lowers a score. True if scam."""
    if legit not in ("scam", "suspicious"):
        return False
    weight = AI_FLAG_SCAM if legit == "scam" else AI_FLAG_SUSPICIOUS
    trust = {**job.data.get("trust", {})}
    scam = {"score": 0, "band": "low", "signals": [], **trust.get("scam", {})}
    if not any(s["code"] == "ai_flag" for s in scam["signals"]):
        evidence = f"AI judged the posting {legit}"
        scam["signals"] = [*scam["signals"], {"code": "ai_flag", "weight": weight,
                                              "evidence": evidence}]  # fmt: skip
        scam["score"] = min(100, scam["score"] + weight)
        score = scam["score"]
        scam["band"] = "low" if score < MEDIUM_FROM else "medium" if score < HIGH_FROM else "high"
    trust["scam"] = scam
    job.data = {**job.data, "trust": trust}
    return legit == "scam"
