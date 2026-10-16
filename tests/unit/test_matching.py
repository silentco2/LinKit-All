import asyncio
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from test_tailor import make_cv

from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobEvent, JobState, Run, RunStatus, Tier, utcnow
from linkit_all.core.profile import ProfileIn, import_profile
from linkit_all.core.runs import current_run
from linkit_all.core.search import SearchConfig
from linkit_all.matching.rank import rank_jobs
from linkit_all.matching.rules import rule_violation, seniority
from linkit_all.matching.score import score_jobs
from linkit_all.providers.base import LLMProvider, UsageLimitError


@pytest.mark.parametrize(
    ("title", "level"),
    [("Senior Backend Engineer", "senior"), ("Engineering Manager", "manager"),
     ("Senior Manager, Data", "manager"), ("Staff Engineer", "lead"), ("Jr. Developer", "junior"),
     ("Software Engineering Intern", "intern"), ("Backend Engineer", "mid"), ("VP Engineering", "executive")],
)  # fmt: skip
def test_seniority(title: str, level: str) -> None:
    assert seniority(title) == level


def job(**kw: Any) -> Job:
    base: dict[str, Any] = {"source": "t", "url": f"https://x/{kw.get('title', 'j')}{kw.get('company', '')}",
                            "title": "Backend Engineer", "company": "Acme", "location": "Cairo, Egypt",
                            "description": "Python APIs", "dedupe_hash": "h", "data": {}}  # fmt: skip
    return Job(**{**base, **kw})


CFG = SearchConfig.model_validate(
    {
        "search": {"posted_within_days": 14},
        "filters": {
            "title_include": ["engineer", "developer"],
            "title_exclude": ["intern"],
            "locations": ["egypt", "remote"],
            "seniority": ["mid", "senior"],
            "salary_floor": 30000,
            "company_blacklist": ["Globex Inc."],
        },
    }
)


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({}, None),
        ({"title": "Data Analyst"}, "include"),
        ({"title": "Backend Engineer Intern"}, "excluded"),
        ({"location": "Berlin, Germany"}, "location"),
        ({"location": "Anywhere", "data": {"remote": "remote"}}, None),
        ({"title": "Lead Engineer"}, "seniority"),
        ({"posted_at": utcnow() - timedelta(days=30)}, "posted"),
        ({"data": {"salary_max": 2000, "salary_interval": "month"}}, "salary"),
        ({"data": {"salary_max": 3000, "salary_interval": "month"}}, None),
        ({"company": "Globex"}, "blacklisted"),
    ],
)
def test_rules(kw: dict[str, Any], reason: str | None) -> None:
    got = rule_violation(job(**kw), CFG, utcnow())
    assert got is None if reason is None else (got is not None and reason in got)


def test_remote_filter() -> None:
    cfg = SearchConfig.model_validate({"filters": {"remote": "remote"}})
    assert rule_violation(job(data={"remote": "remote"}), cfg, utcnow()) is None
    assert "work mode onsite" in (rule_violation(job(), cfg, utcnow()) or "")


def fake_embed(texts: list[str]) -> np.ndarray[Any, np.dtype[np.float64]]:
    rows = []
    for t in texts:
        v = np.zeros(128)
        for w in re.findall(r"\w+", t.lower()):
            v[hash(w) % 128] += 1
        rows.append(v / (np.linalg.norm(v) or 1))
    return np.array(rows)


@pytest.fixture
def db(tmp_path: Path) -> sessionmaker[Session]:
    db = init_db(tmp_path / "t.db")
    cv = make_cv(tmp_path / "cv.docx")  # Python/Go backend engineer
    import_profile(db, ProfileIn(full_name="J", email="j@x.io", cv_path=cv, skills=["Python", "Go"]),
                   tmp_path / "data")  # fmt: skip
    return db


def add(db: sessionmaker[Session], *jobs: Job) -> None:
    with db.begin() as s:
        for j in jobs:
            j.state = JobState.enriched
            s.add(j)


def test_rank_filters_ranks_and_keeps_one_per_company(db: sessionmaker[Session]) -> None:
    add(
        db,
        job(
            title="Backend Engineer",
            company="Acme",
            description="Build scalable backend services in Python and Go",
        ),
        job(title="Backend Developer", company="Acme Inc", description="Java Spring"),
        job(title="Python Engineer", company="Initech", description="Python backend services"),
        job(title="Sales Engineer", company="Hooli", description="Sell enterprise deals, travel"),
        job(title="Data Analyst", company="Umbrella"),
    )
    counts = rank_jobs(db, CFG, fake_embed)
    assert counts == {"ranked": 3, "filtered_out": 2}
    with db() as s:
        ranked = {
            j.title: j.data["rank"] for j in s.scalars(select(Job).filter_by(state=JobState.ranked))
        }
        out = {j.title: s.scalars(select(JobEvent.message).filter_by(job_id=j.id)).one()
               for j in s.scalars(select(Job).filter_by(state=JobState.filtered_out))}  # fmt: skip
    assert set(ranked) == {"Backend Engineer", "Python Engineer", "Sales Engineer"}
    assert ranked["Backend Engineer"] > ranked["Sales Engineer"]
    assert "better match at this company" in out["Backend Developer"]
    assert "include" in out["Data Analyst"]


class FakeAI(LLMProvider):
    name = "fake"

    def __init__(self, scores: dict[str, int], fail_after: int | None = None) -> None:
        super().__init__("fake")
        self.scores, self.calls, self.fail_after = scores, 0, fail_after

    async def _call(self, prompt: str) -> str:
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise UsageLimitError("usage limit reached")
        assert "--- cv start ---" in prompt and "Built scalable" in prompt  # CV text included
        ids = re.findall(r"=== job_id (\d+) ===\n(.+?) at ", prompt)
        results = [{"job_id": int(i), "score": self.scores[title], "reasons": ["fit"]}
                   for i, title in ids if title in self.scores]  # fmt: skip
        import json

        return json.dumps({"results": results})


def ranked_jobs(db: sessionmaker[Session], titles: list[str]) -> None:
    with db.begin() as s:
        for n, t in enumerate(titles):
            s.add(job(title=t, company=t, state=JobState.ranked, data={"rank": 1 - n / 10}))


def test_score_tiers_and_low_rank_cutoff(db: sessionmaker[Session]) -> None:
    ranked_jobs(db, ["A", "B", "C", "D", "E"])
    cfg = SearchConfig.model_validate({"matching": {"ai_max_jobs": 4, "batch_size": 2}})
    ai = FakeAI({"A": 9, "B": 6, "C": 2})  # D is in the top 4 but the AI skips it
    counts = asyncio.run(score_jobs(db, cfg, ai))
    assert counts == {"high": 1, "mid": 1, "low": 2, "not_scored": 1}
    assert ai.calls == 2
    with db() as s:
        by_title = {j.title: j for j in s.scalars(select(Job))}
    assert (by_title["A"].state, by_title["A"].tier, by_title["A"].score) == (
        JobState.queued_apply,
        Tier.high,
        9,
    )
    assert by_title["B"].state == JobState.awaiting_review
    assert by_title["C"].state == JobState.below_threshold and by_title["C"].data["ai"][
        "reasons"
    ] == ["fit"]
    assert by_title["D"].state == JobState.ranked  # retried next run
    assert (by_title["E"].state, by_title["E"].tier, by_title["E"].score) == (
        JobState.below_threshold,
        Tier.low,
        None,
    )


def test_score_pauses_run_on_usage_limit(db: sessionmaker[Session]) -> None:
    ranked_jobs(db, ["A", "B", "C", "D"])
    run_id = current_run(db)
    cfg = SearchConfig.model_validate({"matching": {"batch_size": 2}})
    counts = asyncio.run(
        score_jobs(db, cfg, FakeAI({"A": 9, "B": 9, "C": 9, "D": 9}, fail_after=1), run_id)
    )
    assert counts["high"] == 2 and counts["not_scored"] == 2
    with db() as s:
        run = s.get_one(Run, run_id)
        assert run.status == RunStatus.paused and "usage limit" in (run.pause_reason or "")
        assert s.query(Job).filter_by(state=JobState.ranked).count() == 2


def test_auto_apply_low_off_keeps_lows_below_threshold(db: sessionmaker[Session]) -> None:
    ranked_jobs(db, ["A", "B"])
    asyncio.run(score_jobs(db, SearchConfig.model_validate({"matching": {"ai_max_jobs": 1}}),
                           FakeAI({"A": 2})))  # fmt: skip
    with db() as s:
        states = {j.title: j.state for j in s.scalars(select(Job))}
    assert states == {"A": JobState.below_threshold, "B": JobState.below_threshold}


def test_auto_apply_low_queues_lows_and_requeues_old_ones(db: sessionmaker[Session]) -> None:
    ranked_jobs(db, ["A", "B", "C"])
    off = SearchConfig.model_validate({"matching": {"ai_max_jobs": 2}})
    asyncio.run(score_jobs(db, off, FakeAI({"A": 9, "B": 2})))  # B AI-low, C outside the top 2
    with db.begin() as s:
        s.add(job(title="Out", company="Out", state=JobState.filtered_out))
        s.add(job(title="New", company="New", state=JobState.ranked, data={"rank": 0.1}))
    on = SearchConfig.model_validate({"matching": {"ai_max_jobs": 2, "auto_apply_low": True}})
    counts = asyncio.run(score_jobs(db, on, FakeAI({"New": 3})))
    assert counts["requeued_low"] == 2 and counts["low"] == 1
    with db() as s:
        jobs = {j.title: j for j in s.scalars(select(Job))}
        msgs = {
            t: s.scalars(
                select(JobEvent.message).filter_by(job_id=j.id, to_state=JobState.queued_apply)
            ).all()
            for t, j in jobs.items()
        }
    assert jobs["Out"].state == JobState.filtered_out
    for t in ("B", "C", "New"):  # AI-scored low, not-scored low, new AI-scored low
        assert jobs[t].state == JobState.queued_apply and jobs[t].tier == Tier.low
        assert "low-tier auto-apply opt-in" in msgs[t][0]
    assert jobs["A"].state == JobState.queued_apply and "opt-in" not in msgs["A"][0]
    # ordering used by pick_jobs: score first, then rank; unscored lows sort last
    order = sorted(jobs.values(), key=lambda j: (-(j.score or 0), -(j.data.get("rank") or 0)))
    assert next(j.title for j in order if j.state == JobState.queued_apply) == "A"
