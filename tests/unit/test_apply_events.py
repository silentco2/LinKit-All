"""Per-job apply log events: a start line, then an outcome with a stable reason (Activity view)."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from loguru import logger
from test_apply_skip import NoAI
from test_matching import fake_embed

from linkit_all.apply import runner
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import ActionKind, Job, JobState, Profile
from linkit_all.core.search import SearchConfig
from linkit_all.core.state import transition


class Page:
    async def close(self) -> None: ...


class Browser:
    async def new_page(self) -> Page:
        return Page()


def test_start_event_then_outcome_with_reason_and_questions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    with db.begin() as s:
        s.add(Profile(id=1, full_name="Me", cv_path="cv.docx", email="me@example.com"))
        for i in range(6):
            s.add(Job(source="x", url=f"https://jobs.lever.co/a/{i}", title=f"Dev {i}",
                      company=f"C{i}", location="", description="", ats="lever",
                      dedupe_hash=str(i), score=9 - i, state=JobState.tailored,
                      data={"apply_url": f"https://jobs.lever.co/a/{i}"}))  # fmt: skip
    ids = [1, 2, 3, 4, 5, 6]

    class PW:
        async def stop(self) -> None: ...

    class Starter:
        async def start(self) -> PW:
            return PW()

    async def never_closed(*_: Any) -> bool:
        return False

    async def cv(*_: Any) -> str:
        return "cv.pdf"

    async def browser(*_: Any) -> Browser:
        return Browser()

    async def nothing(*_: Any) -> None: ...

    async def boom(*_: Any, **__: Any) -> runner.Outcome:
        raise ValueError("form exploded")

    async def idle(*_: Any, **__: Any) -> None:
        await asyncio.sleep(3600)

    real_apply = runner.Applier.apply

    async def fake_apply(self: runner.Applier, job_id: int) -> runner.Outcome:
        if job_id == 4:  # the real code path, so the crash handler runs
            return await real_apply(self, job_id)
        with db.begin() as s:
            job = s.get_one(Job, job_id)
            if job_id == 1:  # parked with two open questions
                questions = [{"label": "Why us?"}, {"label": "Notice period?"}]
                runner._park(s, job, ActionKind.unknown_question, "2 need you", questions, {},
                             [], "unknown_question", {"n": 2})  # fmt: skip
                return runner.Outcome("needs_user", "2 questions need you")
            if job_id == 2:
                transition(s, job, JobState.skipped, "closed", code="job_closed")
                return runner.Outcome("skipped", "closed")
            if job_id == 3:
                transition(s, job, JobState.applying, "filling", code="filling")
                transition(s, job, JobState.failed, "no page", code="no_confirmation")
                return runner.Outcome("failed", "no confirmation seen")
            if job_id == 5:  # no event of its own: the outcome names the reason
                return runner.Outcome("skipped", "no form handler", reason="no_handler")
        return runner.Outcome("dry_run", "filled")

    monkeypatch.setattr(runner, "async_playwright", Starter)
    monkeypatch.setattr(runner, "live_frames", idle)
    monkeypatch.setattr(runner.Applier, "pick_jobs", lambda _self: ids)
    monkeypatch.setattr(runner.Applier, "apply", fake_apply)
    monkeypatch.setattr(runner.Applier, "_posting_closed", never_closed)
    monkeypatch.setattr(runner.Applier, "_cv_pdf", cv)
    monkeypatch.setattr(runner.Applier, "_context", browser)
    monkeypatch.setattr(runner.Applier, "_trace_start", nothing)
    monkeypatch.setattr(runner.Applier, "_trace_stop", nothing)
    monkeypatch.setattr(runner.Applier, "_fill_and_decide", boom)
    monkeypatch.setattr(runner.random, "uniform", lambda *_: 0.0)

    lines: list[tuple[str, dict[str, Any]]] = []
    sink = logger.add(
        lambda m: (
            lines.append((m.record["extra"].get("code", ""), m.record["extra"]["params"]))
            if "code" in m.record["extra"]
            else None
        ),
        level="INFO",
    )
    try:
        cfg = SearchConfig.model_validate({"apply": {"parallel_sites": 1}})
        asyncio.run(runner.apply_jobs(db, settings, cfg, NoAI(), fake_embed))
    finally:
        logger.remove(sink)

    codes = [c for c, _ in lines]
    outcome = {p["job"]: p for c, p in lines if c == "apply_job"}
    started = {p["job"]: i for i, (c, p) in enumerate(lines) if c == "apply_job_start"}
    finished = {p["job"]: i for i, (c, p) in enumerate(lines) if c == "apply_job"}
    assert all(started[j] < finished[j] for j in ids)  # start comes before the outcome
    assert lines[started[1]][1] == {"job": 1, "title": "Dev 0", "company": "C0"}

    assert outcome[1] == {"job": 1, "status": "needs_user", "reason": "unknown_question",
                          "questions": 2}  # fmt: skip
    assert outcome[2] == {"job": 2, "status": "skipped", "reason": "job_closed"}
    assert outcome[3] == {"job": 3, "status": "failed", "reason": "no_confirmation"}
    assert outcome[5] == {"job": 5, "status": "skipped", "reason": "no_handler"}
    assert outcome[6] == {"job": 6, "status": "dry_run"}  # no reason on a clean outcome

    assert outcome[4] == {"job": 4, "status": "failed", "reason": "apply_crashed"}
    (crash,) = [p for c, p in lines if c == "apply_crashed"]
    assert crash == {"job": 4, "error": "ValueError: form exploded"}
    assert codes.index("apply_crashed") < finished[4]  # logged before the outcome line
