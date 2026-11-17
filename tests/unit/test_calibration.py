"""Outcome calibration in the report (C4): advisory, with a minimum sample per group."""

from pathlib import Path

from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobState, Outcome
from linkit_all.reports import MIN_SAMPLE, build_report


def add(
    s, n: int, score: int | None, ats: str, outcome: Outcome | None, state=JobState.applied
) -> None:  # type: ignore[no-untyped-def]
    for _ in range(n):
        i = add.count = getattr(add, "count", 0) + 1  # type: ignore[attr-defined]
        s.add(Job(source="greenhouse_src", url=f"https://x.io/{i}", title="Dev", company=f"C{i}",
                  dedupe_hash=str(i), state=state, score=score, ats=ats, outcome=outcome))  # fmt: skip


def test_rates_per_band_ats_and_source(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    with db.begin() as s:
        add(s, 2, 9, "greenhouse", Outcome.interview)
        add(s, 1, 9, "greenhouse", Outcome.offer)
        add(s, 3, 8, "greenhouse", None)  # no reply yet still counts as applied
        add(s, 4, 6, "lever", Outcome.rejected)  # 4 < MIN_SAMPLE: no rate
        add(s, 5, 9, "greenhouse", Outcome.interview, JobState.queued_apply)  # not applied
    with db() as s:
        cal = build_report(s)["calibration"]
    assert cal["min_sample"] == MIN_SAMPLE == 5
    bands = {r["name"]: r for r in cal["by_band"]}
    assert bands["strong"] == {"name": "strong", "applied": 6, "interviews": 3, "rate": 0.5,
                               "enough": True}  # fmt: skip
    assert bands["possible"] == {"name": "possible", "applied": 4, "interviews": 0,
                                 "rate": None, "enough": False}  # fmt: skip
    assert {r["name"]: r["rate"] for r in cal["by_ats"]} == {"greenhouse": 0.5, "lever": None}
    assert cal["by_source"] == [{"name": "greenhouse_src", "applied": 10, "interviews": 3,
                                 "rate": 0.3, "enough": True}]  # fmt: skip


def test_no_applications_means_empty_tables(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    with db() as s:
        cal = build_report(s)["calibration"]
    assert (cal["by_band"], cal["by_ats"], cal["by_source"]) == ([], [], [])
