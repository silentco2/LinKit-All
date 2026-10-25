"""The message-code migration upgrades an existing database and keeps its old rows."""

from pathlib import Path

from alembic import command
from sqlalchemy import text

from linkit_all.core.db import alembic_config, make_engine


def test_codes_migration_keeps_old_rows(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "old.db")
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "b0a4d7e2c158")  # the head before D3
        conn.execute(
            text(
                "INSERT INTO jobs (source, url, title, company, location, description,"
                " dedupe_hash, state, tier, data, created_at, updated_at) VALUES"
                " ('x', 'https://x/1', 'Dev', 'Acme', '', '', 'h', 'needs_user', 'high',"
                " '{}', '2026-10-17', '2026-10-17')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO action_items (job_id, kind, status, message, questions, answers,"
                " artifacts, created_at) VALUES (1, 'captcha', 'open', 'a CAPTCHA appeared',"
                " '[]', '{}', '[]', '2026-10-17')"
            )
        )
        command.upgrade(cfg, "head")
        row = conn.execute(text("SELECT message, code, params FROM action_items")).one()
        assert (row[0], row[1], row[2]) == ("a CAPTCHA appeared", None, "{}")
        conn.execute(text("SELECT code, params FROM job_events")).fetchall()
