from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.db import init_db
from linkit_all.core.models import Job, JobEvent, JobState
from linkit_all.core.state import ALLOWED, InvalidTransition, transition

S = JobState


@pytest.fixture
def db(tmp_path: Path) -> sessionmaker[Session]:
    return init_db(tmp_path / "t.db")


def _job(session: Session) -> Job:
    job = Job(source="test", url="https://x/1", title="Dev", company="Acme", dedupe_hash="h")
    session.add(job)
    session.flush()
    return job


def test_migrations_create_wal_db(db: sessionmaker[Session]) -> None:
    with db() as s:
        assert s.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert s.execute(text("SELECT count(*) FROM jobs")).scalar() == 0


def test_happy_path_writes_events(db: sessionmaker[Session]) -> None:
    path = [S.enriched, S.ranked, S.scored, S.queued_apply, S.tailored, S.applying, S.applied]
    with db() as s:
        job = _job(s)
        for state in path:
            assert transition(s, job, state, artifacts=["a.pdf"] if state == S.tailored else ())
        s.commit()
        events = s.query(JobEvent).filter_by(job_id=job.id).all()
    assert [e.to_state for e in events] == path
    assert events[0].from_state == S.discovered
    assert events[4].artifacts == ["a.pdf"]


def test_invalid_transition_raises_and_writes_nothing(db: sessionmaker[Session]) -> None:
    with db() as s:
        job = _job(s)
        with pytest.raises(InvalidTransition):
            transition(s, job, S.applied)
        assert job.state == S.discovered
        assert s.query(JobEvent).count() == 0


def test_same_state_is_noop(db: sessionmaker[Session]) -> None:
    with db() as s:
        job = _job(s)
        assert transition(s, job, S.enriched)
        assert not transition(s, job, S.enriched)
        assert s.query(JobEvent).count() == 1


def test_skip_allowed_until_terminal(db: sessionmaker[Session]) -> None:
    with db() as s:
        job = _job(s)
        assert transition(s, job, S.skipped)
        with pytest.raises(InvalidTransition):
            transition(s, job, S.enriched)


def test_every_state_has_rules() -> None:
    assert set(ALLOWED) == set(JobState)
