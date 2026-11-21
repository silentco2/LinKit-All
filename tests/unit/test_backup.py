"""B3 database backups (core/backup.py): daily consistent copies, 7 kept, a folder setting,
`linkit backup` / `linkit restore`, and Settings > Advanced status + "Back up now"."""

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_api import SAME_ORIGIN, client  # noqa: F401
from typer.testing import CliRunner

from linkit_all.cli import app as cli
from linkit_all.core import backup
from linkit_all.core.config import get_settings
from linkit_all.core.db import init_db
from linkit_all.core.models import Job
from linkit_all.core.search import BackupSection, SearchConfig, save_search

T0 = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)


def _db(path: Path, title: str = "Backend Engineer") -> Path:
    db = init_db(path)
    with db.begin() as s:
        s.add(
            Job(
                source="t", url=f"https://x/{title}", title=title, company="Acme", dedupe_hash=title
            )
        )
    db.kw["bind"].dispose()
    return path


def _titles(path: Path) -> list[str]:
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("SELECT title FROM jobs ORDER BY id")]
    finally:
        con.close()


def test_daily_copies_keep_the_newest_seven(tmp_path: Path) -> None:
    db, folder = _db(tmp_path / "linkit.db"), tmp_path / "backups"
    assert backup.due(folder)
    for day in range(9):
        made = backup.backup(db, folder, T0 + timedelta(days=day))
    have = backup.copies(folder)
    assert len(have) == backup.KEEP and have[-1] == made and _titles(made) == ["Backend Engineer"]
    assert have[0].name == "linkit-20261122-090000.db"  # the two oldest were dropped
    assert not backup.due(folder, T0 + timedelta(days=8, hours=23))
    assert backup.due(folder, T0 + timedelta(days=9))


def test_restore_puts_a_copy_back_and_saves_the_current_one(tmp_path: Path) -> None:
    db, folder = _db(tmp_path / "linkit.db", "Old Job"), tmp_path / "backups"
    for day in range(7):
        backup.backup(db, folder, T0 + timedelta(days=day))
    oldest = backup.copies(folder)[0]
    con = sqlite3.connect(db)
    con.execute("UPDATE jobs SET title = 'Changed Since'")
    con.commit()
    con.close()
    saved = backup.restore(db, oldest, folder)  # the oldest of 7: the safety copy must not prune it
    assert saved is not None and saved.name.startswith("linkit-before-restore-")
    assert _titles(db) == ["Old Job"] and _titles(saved) == ["Changed Since"]
    assert len(backup.copies(folder)) == backup.KEEP and oldest.exists()


def test_restore_refuses_what_is_not_a_linkit_database(tmp_path: Path) -> None:
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"not sqlite at all")
    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("CREATE TABLE t (x)").connection.close()
    for bad in (junk, other):
        with pytest.raises(ValueError):
            backup.check(bad)


def test_folder_setting(tmp_path: Path) -> None:
    assert backup.folder_for(tmp_path, "") == tmp_path / "backups"
    assert backup.folder_for(tmp_path, str(tmp_path / "elsewhere")) == tmp_path / "elsewhere"
    with pytest.raises(ValidationError):
        BackupSection(folder="relative/backups")
    db_path = tmp_path / "linkit.db"
    db = init_db(db_path)
    cfg = SearchConfig()
    cfg.backup.folder = str(tmp_path / "elsewhere")
    save_search(db, cfg)
    db.kw["bind"].dispose()
    assert backup.saved_folder(db_path) == str(tmp_path / "elsewhere")
    assert backup.saved_folder(tmp_path / "missing.db") == ""


def test_the_open_app_backs_up_when_due(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _db(tmp_path / "linkit.db")
    db = init_db(path)

    async def stop(_: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(backup.asyncio, "sleep", stop)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(backup.keep_backing_up(db, path, tmp_path))
    assert len(backup.copies(tmp_path / "backups")) == 1


def test_backup_api(client: TestClient, tmp_path: Path) -> None:  # noqa: F811
    folder = tmp_path / "chosen"
    cfg = client.get("/api/search").json()
    cfg["backup"] = {"folder": str(folder)}
    assert client.put("/api/search", json=cfg, headers=SAME_ORIGIN).status_code == 200
    assert client.get("/api/backup").json()["folder"] == str(folder)
    made = client.post("/api/backup", headers=SAME_ORIGIN).json()
    assert made["count"] == 1 and made["last"].startswith("linkit-") and made["last_at"]
    cfg["backup"] = {"folder": "not/absolute"}
    assert client.put("/api/search", json=cfg, headers=SAME_ORIGIN).status_code == 422


def test_cli_backup_and_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data = tmp_path / "data"
    monkeypatch.setenv("LINKIT_DATA_DIR", str(data))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        assert runner.invoke(cli, ["backup"]).exit_code == 1  # no database yet
        _db(data / "linkit.db", "Kept Job")
        out = runner.invoke(cli, ["backup"])
        assert out.exit_code == 0 and "Backed up to" in out.output
        copy = backup.copies(data / "backups")[0]
        con = sqlite3.connect(data / "linkit.db")
        con.execute("UPDATE jobs SET title = 'Lost Job'")
        con.commit()
        con.close()
        assert runner.invoke(cli, ["restore", str(copy)], input="n\n").exit_code == 1  # asked first
        assert _titles(data / "linkit.db") == ["Lost Job"]
        out = runner.invoke(cli, ["restore", str(copy), "--yes"])
        assert out.exit_code == 0 and _titles(data / "linkit.db") == ["Kept Job"]
        assert runner.invoke(cli, ["restore", str(tmp_path / "nope.db"), "--yes"]).exit_code == 1
    finally:
        get_settings.cache_clear()
