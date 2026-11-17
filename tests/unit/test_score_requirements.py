"""B3 requirement importance and B4 score confidence (matching/score.py)."""

import asyncio
import json
from typing import Any

from sqlalchemy.orm import Session, sessionmaker
from test_matching import db  # noqa: F401  (fixture)

from linkit_all.core.models import Job, JobState, Tier
from linkit_all.core.search import SearchConfig
from linkit_all.matching.score import (
    JD_CHARS,
    MAX_REQUIREMENTS,
    JobScore,
    ScoreBatch,
    confidence_of,
    score_jobs,
)
from linkit_all.providers.base import LLMProvider, render

LONG = "We build payment systems for banks across the region. " * 10  # 540 characters


def req(**kw: Any) -> dict[str, Any]:
    return {"text": "Python", "importance": "high", "basis": "stated", "met": "yes", **kw}


def scored(**kw: Any) -> JobScore:
    return JobScore.model_validate({"job_id": 1, "score": 7, **kw})


def test_inferred_requirement_is_never_critical_or_high() -> None:
    got = scored(
        requirements=[
            req(importance="critical", basis="inferred"),
            req(importance="high", basis="inferred"),
            req(importance="critical", basis="stated"),
            req(importance="high", basis="structural"),
            req(importance="preferred", basis="inferred"),
        ]
    ).requirements
    assert [r.importance for r in got] == ["meaningful", "meaningful", "critical", "high", "preferred"]  # fmt: skip


def test_old_cached_response_without_the_fields_still_parses() -> None:
    old = '{"results": [{"job_id": 3, "score": 8, "reasons": ["fits"], "legit": "ok"}]}'
    got = ScoreBatch.model_validate_json(old).results[0]
    assert (got.requirements, got.cv_evidence, got.score) == ([], "found", 8)


def test_unknown_values_are_read_as_defaults_and_the_list_is_capped() -> None:
    odd = scored(
        requirements=[req(importance="vital", basis="hunch", met="maybe")] + [req()] * 12,
        cv_evidence="none",
    )
    first = odd.requirements[0]
    assert (first.importance, first.basis, first.met) == ("meaningful", "inferred", "partial")
    assert len(odd.requirements) == MAX_REQUIREMENTS
    assert odd.cv_evidence == "found"


def test_prompt_asks_for_requirements_and_keeps_the_score_rule() -> None:
    prompt = render(
        "score.j2",
        cv="cv",
        prefs={"titles": "", "locations": "", "work_modes": "remote", "seniority": ""},
        jobs=[],
    )
    assert "`requirements`" in prompt and "`cv_evidence`" in prompt
    assert "9-10 strong fit" in prompt


def test_confidence_levels() -> None:
    stated = scored(requirements=[req()])
    assert confidence_of(LONG, stated) == "high"
    assert confidence_of(LONG, scored()) == "medium"  # no requirements listed
    assert confidence_of(LONG, scored(requirements=[req(basis="inferred")])) == "medium"
    assert confidence_of("x" * (JD_CHARS + 1), stated) == "medium"  # the AI read only a part
    assert confidence_of("Short ad.", stated) == "low"
    assert confidence_of(LONG.strip() + "...", stated) == "low"  # cut by the source
    assert confidence_of(LONG, scored(requirements=[req()], cv_evidence="missing")) == "low"


class OneScore(LLMProvider):
    name = "fake"

    def __init__(self) -> None:
        super().__init__("fake")

    async def _call(self, prompt: str) -> str:
        return json.dumps(
            {"results": [{"job_id": 1, "score": 9, "cv_evidence": "missing",
                          "requirements": [req(importance="critical", basis="inferred")]}]}
        )  # fmt: skip


def test_score_stores_confidence_and_never_changes_the_tier(
    db: sessionmaker[Session],  # noqa: F811
) -> None:
    with db.begin() as s:
        s.add(Job(source="x", url="https://x.test/1", title="Dev", company="Acme", location="",
                  dedupe_hash="h", description=LONG, state=JobState.ranked, data={"rank": 0.9}))  # fmt: skip
    asyncio.run(score_jobs(db, SearchConfig(), OneScore()))  # the reply names job_id 1
    with db() as s:
        job = s.get_one(Job, 1)
        assert job.data["confidence"] == "low"
        assert (job.tier, job.state) == (Tier.high, JobState.queued_apply)  # 9 is still high
        assert job.data["ai"]["requirements"][0]["importance"] == "meaningful"
