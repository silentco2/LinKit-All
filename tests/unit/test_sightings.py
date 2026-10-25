"""Repeat sightings of a job across runs, and the migration that adds the table."""

from pathlib import Path

from alembic import command
from sqlalchemy import select, text

from linkit_all.core.db import alembic_config, init_db, make_engine
from linkit_all.core.models import Job, JobSighting, Run
from linkit_all.core.sightings import first_seen, seen_runs
from linkit_all.sources.base import JobStub
from linkit_all.sources.store import Deduper, store_page


def stub(
    title: str = "Backend Engineer", url: str = "https://x.io/1", loc: str = "Cairo"
) -> JobStub:
    return JobStub(source="t", url=url, title=title, company="Acme", location=loc)


def run_page(db, stubs: list[JobStub]) -> int:  # type: ignore[no-untyped-def]
    """A fresh run that stores one page, like discovery does."""
    with db.begin() as s:
        run = Run()
        s.add(run)
        s.flush()
        run_id = run.id
        d = Deduper(s)
    store_page(db, run_id, "k", 0, stubs, d)
    return run_id


def sightings(db) -> list[tuple[int, int | None]]:  # type: ignore[no-untyped-def]
    with db() as s:
        return [(r.job_id, r.run_id) for r in s.scalars(select(JobSighting))]


def test_new_job_has_one_sighting(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    r1 = run_page(db, [stub()])
    assert sightings(db) == [(1, r1)]
    with db() as s:
        assert first_seen(s, 1) is not None
        assert first_seen(s, 99) is None


def test_repeat_in_later_run_via_url_hash_fuzzy(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    run_page(db, [stub()])
    run_page(db, [stub(title="Other", url="https://x.io/1?utm_source=a")])  # url
    run_page(db, [stub(url="https://y.io/9")])  # hash
    run_page(db, [stub(title="Engineer, Backend", url="https://z.io/3")])  # fuzzy
    with db() as s:
        assert s.scalars(select(Job)).all().__len__() == 1
        assert seen_runs(s, [1, 2]) == {1: 4}


def test_same_job_twice_in_one_run_counts_once(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    with db.begin() as s:
        run = Run()
        s.add(run)
        s.flush()
        run_id = run.id
        d = Deduper(s)
    store_page(db, run_id, "k", 0, [stub(), stub(url="https://y.io/9")], d)  # same page
    store_page(db, run_id, "k", 1, [stub(url="https://z.io/8")], d)  # later page
    assert sightings(db) == [(1, run_id)]
    with db() as s:
        assert seen_runs(s, [1]) == {1: 1}


def test_migration_adds_table_and_backfills(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "old.db")
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "d3a1c5e7f902")  # the head before G1
        conn.execute(
            text(
                "INSERT INTO jobs (source, url, title, company, location, description,"
                " dedupe_hash, state, data, created_at, updated_at) VALUES"
                " ('x', 'https://x/1', 'Dev', 'Acme', '', '', 'h', 'discovered',"
                " '{}', '2026-10-17', '2026-10-17')"
            )
        )
        command.upgrade(cfg, "head")
        row = conn.execute(text("SELECT job_id, run_id, url, source FROM job_sightings")).one()
        assert tuple(row) == (1, None, "https://x/1", "x")
