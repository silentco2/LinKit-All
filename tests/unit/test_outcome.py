"""Job outcomes after applying (C1): a field beside the state machine, never a new state."""

from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from test_api import SAME_ORIGIN, client  # noqa: F401 - the fixture

from linkit_all.core.db import alembic_config, init_db, make_engine
from linkit_all.core.models import Job, JobState, Outcome
from linkit_all.core.state import ALLOWED, TERMINAL, NotApplied, can_transition, set_outcome


def job(db, state: JobState = JobState.applied) -> int:  # type: ignore[no-untyped-def]
    with db.begin() as s:
        j = Job(source="t", url=f"https://x.io/{state}", title="Dev", company="Acme",
                dedupe_hash="h", state=state)  # fmt: skip
        s.add(j)
        s.flush()
        return j.id


def test_set_outcome_logs_an_event_and_keeps_the_state(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    jid = job(db)
    with db.begin() as s:
        j = s.get_one(Job, jid)
        assert set_outcome(s, j, Outcome.interview, "email")
        assert not set_outcome(s, j, Outcome.interview)  # same again: no-op
        assert set_outcome(s, j, Outcome.rejected)
    with db() as s:
        j = s.get_one(Job, jid)
        assert (j.state, j.outcome) == (JobState.applied, Outcome.rejected)
        assert j.outcome_at is not None
        events = [e for e in j.events if e.code == "outcome"]
        assert [e.params["outcome"] for e in events] == ["interview", "rejected"]
        assert events[0].params["source"] == "email"
        assert events[1].params["was"] == "interview"


def test_only_applied_jobs_have_an_outcome(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    jid = job(db, JobState.queued_apply)
    with db.begin() as s, pytest.raises(NotApplied):
        set_outcome(s, s.get_one(Job, jid), Outcome.offer)


def test_applied_is_still_terminal() -> None:
    assert ALLOWED[JobState.applied] == frozenset()
    assert JobState.applied in TERMINAL
    assert not any(can_transition(JobState.applied, to) for to in JobState)


def test_migration_adds_and_drops_the_columns(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "old.db")
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "c8f6b0d2e457")  # the head before C1
        conn.execute(
            text(
                "INSERT INTO jobs (source, url, title, company, location, description,"
                " dedupe_hash, state, data, created_at, updated_at) VALUES"
                " ('x', 'https://x/1', 'Dev', 'Acme', '', '', 'h', 'applied',"
                " '{}', '2026-11-01', '2026-11-01')"
            )
        )
        command.upgrade(cfg, "d9a7c1e3f568")
        cols = {c["name"] for c in inspect(conn).get_columns("jobs")}
        assert {"outcome", "outcome_at"} <= cols
        assert conn.execute(text("SELECT outcome FROM jobs")).scalar() is None
        command.downgrade(cfg, "c8f6b0d2e457")
        cols = {c["name"] for c in inspect(conn).get_columns("jobs")}
        assert "outcome" not in cols and "outcome_at" not in cols


def test_outcome_api(client: TestClient) -> None:  # noqa: F811 - pytest fixture
    db = client.app.state.db  # type: ignore[attr-defined]
    applied, queued = job(db), job(db, JobState.queued_apply)
    r = client.post(f"/api/jobs/{applied}/outcome", json={"outcome": "offer"}, headers=SAME_ORIGIN)
    assert r.status_code == 200 and r.json()["outcome"] == "offer"
    assert client.get(f"/api/jobs/{applied}").json()["outcome"] == "offer"
    r = client.post(f"/api/jobs/{queued}/outcome", json={"outcome": "offer"}, headers=SAME_ORIGIN)
    assert r.status_code == 409
    bad = client.post(
        f"/api/jobs/{applied}/outcome", json={"outcome": "maybe"}, headers=SAME_ORIGIN
    )
    assert bad.status_code == 422
    missing = client.post("/api/jobs/9999/outcome", json={"outcome": "offer"}, headers=SAME_ORIGIN)
    assert missing.status_code == 404
