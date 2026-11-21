"""Daily copies of the database (profile, answers, every job, the applied history, outcomes and
the vault, which stays encrypted): SQLite's own backup API, so a copy is consistent while the app
runs. One a day while the app is open, the newest KEEP kept, in `<data dir>/backups` or the folder
set in `backup.folder` (maintainer 2026-11-20). CV files are not copied. `linkit backup` makes one
now; `linkit restore FILE` puts one back after saving the current database beside it."""

import asyncio
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.search import load_search

KEEP = 7
EVERY = timedelta(hours=24)
CHECK_S = 3600  # how often the open app looks whether a copy is due
PREFIX = "linkit-"
_STAMP = "%Y%m%d-%H%M%S"


def folder_for(data_dir: Path, setting: str) -> Path:
    """`backup.folder` when set, else `<data dir>/backups`."""
    return Path(setting).expanduser() if setting.strip() else data_dir / "backups"


def saved_folder(db_path: Path) -> str:
    """`backup.folder` read straight from the database file (read-only, closed at once), for
    the CLI, which must not hold the file open while it restores over it."""
    try:
        con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        try:
            row = con.execute("SELECT data FROM search_config WHERE id = 1").fetchone()
        finally:
            con.close()
        return str(json.loads(row[0]).get("backup", {}).get("folder", "")) if row else ""
    except (sqlite3.Error, ValueError, AttributeError):
        return ""


def copies(folder: Path) -> list[Path]:
    """Backups in `folder`, oldest first (by the time in their name)."""
    return sorted(folder.glob(f"{PREFIX}2*.db")) if folder.is_dir() else []


def _taken(path: Path) -> datetime:
    return datetime.strptime(path.stem.removeprefix(PREFIX), _STAMP).replace(tzinfo=UTC)


def due(folder: Path, now: datetime | None = None) -> bool:
    have = copies(folder)
    return not have or (now or datetime.now(UTC)) - _taken(have[-1]) >= EVERY


def backup(db_path: Path, folder: Path, now: datetime | None = None, kind: str = "") -> Path:
    """Copy the database into `folder` now; drop all but the newest KEEP daily copies. Returns the
    new copy. A `kind` copy ("before-restore") is named apart and never counted or pruned."""
    folder.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(UTC)).strftime(_STAMP)
    out = folder / f"{PREFIX}{kind + '-' if kind else ''}{stamp}.db"
    tmp = out.with_suffix(".tmp")
    src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    tmp.replace(out)
    for old in copies(folder)[:-KEEP]:
        old.unlink(missing_ok=True)
    return out


def check(path: Path) -> None:
    """ValueError unless `path` is a sound LinKit All database."""
    try:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            rows = con.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in rows}
        finally:
            con.close()
    except sqlite3.Error as e:
        raise ValueError(f"{path.name} is not a database that can be read") from e
    if ok != "ok" or not {"jobs", "profile"} <= tables:
        raise ValueError(f"{path.name} is not a sound LinKit All database")


def restore(db_path: Path, path: Path, folder: Path) -> Path | None:
    """Put the copy at `path` back as the database. The app must be closed. The current database
    is saved into `folder` first (returned; None when there was none)."""
    check(path)
    saved = backup(db_path, folder, kind="before-restore") if db_path.exists() else None
    for end in ("-wal", "-shm"):  # they belong to the old file
        db_path.with_name(db_path.name + end).unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(db_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return saved


async def keep_backing_up(db: sessionmaker[Session], db_path: Path, data_dir: Path) -> None:
    """While the app is open: a copy when the newest one is a day old (also right at start)."""
    while True:
        try:
            cfg = load_search(db)
            folder = folder_for(data_dir, cfg.backup.folder if cfg else "")
            if due(folder):
                made = await asyncio.to_thread(backup, db_path, folder)
                logger.info("database backed up to {}", made)
        except Exception as e:  # a full disk or a missing folder must not stop the app
            logger.warning("database backup failed ({}: {})", type(e).__name__, e)
        await asyncio.sleep(CHECK_S)
