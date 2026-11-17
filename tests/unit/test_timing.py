"""Step timings: own time per step, slow steps kept with why, and the scorecard's summary."""

import asyncio
import time
from datetime import datetime

from linkit_all.apply.probe import ProbeRow, scorecard
from linkit_all.core import timing


def test_a_step_counts_only_its_own_time_and_slow_ones_keep_their_note(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(timing, "SLOW_S", 0.04)
    t = timing.start()
    try:
        with timing.step("load page"):
            time.sleep(0.05)
            with timing.step("AI FieldMap"):
                timing.note("fresh call")
                time.sleep(0.05)
        with timing.step("AI FieldMap"):
            pass
    finally:
        timing.stop()
    s = t.summary()
    load, ai = s["steps"]["load page"], s["steps"]["AI FieldMap"]
    assert 0.04 < load[0] < 0.09 and ai[1] == 2  # the inner step is not counted twice
    assert {"step": "AI FieldMap", "s": 0.1, "note": "fresh call"} in s["slow"] or any(
        x["step"] == "AI FieldMap" and x["note"] == "fresh call" for x in s["slow"]
    )
    assert s["total"] >= load[0] + ai[0]


def test_outside_an_application_timing_does_nothing() -> None:
    with timing.step("x"):
        timing.note("ignored")  # no Timings started: no error, nothing kept


def test_each_job_task_keeps_its_own_timings() -> None:
    async def job(name: str) -> dict[str, list[float]]:
        t = timing.start()
        with timing.step(name):
            await asyncio.sleep(0.01)
        return t.summary()["steps"]

    async def both() -> list[dict[str, list[float]]]:
        return await asyncio.gather(job("a"), job("b"))

    a, b = asyncio.run(both())
    assert "a" in a and "b" not in a and "b" in b


def test_the_scorecard_says_where_the_time_went_and_the_pass_rate() -> None:
    def row(
        n: int, status: str, code: str, steps: dict[str, list[float]], slow: list[dict]
    ) -> ProbeRow:  # type: ignore[type-arg]
        t = {"total": sum(s for s, _ in steps.values()), "steps": steps, "slow": slow}
        return ProbeRow(n, "src", "h.io", status, "", code, "", "form agent", t["total"], t)

    rows = [
        row(1, "dry_run", "dry_run_agent", {"AI FieldMap": [8.0, 1], "load page": [2.0, 1]},
            [{"step": "AI FieldMap", "s": 8.0, "note": "claude_cli, 12k-character prompt"}]),
        row(2, "dry_run", "dry_run_signup", {"AI FieldMap": [6.0, 1], "wait for page": [10.0, 1]},
            [{"step": "wait for page", "s": 10.0, "note": "never went quiet after 10 s"}]),
        row(3, "needs_user", "unknown_question", {"AI Drafts": [4.0, 1]}, []),
        row(4, "needs_user", "apply_in_browser", {"open browser": [1.0, 1]}, []),
        row(5, "failed", "apply_crashed", {"load page": [30.0, 1]}, []),
    ]  # fmt: skip
    text = scorecard(rows, datetime(2026, 11, 13))
    # LinkedIn and the user's own question are listed but not counted
    assert "**Pass rate: 2 of 3 (67%)**" in text and "1 LinkedIn" in text and "1 waiting" in text
    assert "## Where the time goes" in text
    assert "| load page | 2 | 16.0 s | 30 s | 52% |" in text  # 32 of 61 s
    assert "claude_cli, Nk-character prompt (1 jobs)" in text  # numbers grouped away
    assert "h.io" not in text
