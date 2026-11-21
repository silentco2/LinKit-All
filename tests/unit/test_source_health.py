"""B2 source health (sources/health.py): each switched-on source's and company page's last result,
from discover runs and live checks; broken = an error with no jobs, or 3 empty runs after jobs."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.orm import Session, sessionmaker
from test_api import SAME_ORIGIN, client  # noqa: F401
from typer.testing import CliRunner

from linkit_all import pipeline
from linkit_all.cli import app as cli
from linkit_all.core.db import alembic_config, init_db, make_engine
from linkit_all.core.models import SourceHealth, utcnow
from linkit_all.core.runs import current_run
from linkit_all.core.search import SearchConfig
from linkit_all.sources import health
from linkit_all.sources.base import JobStub, Source, Task
from linkit_all.sources.http import Http
from linkit_all.sources.runner import discover


class Fake(Source):
    """An opt-in board whose answers the test sets: a number of jobs, or an error."""

    kind = "board"

    def __init__(self, name: str, jobs: int = 0, error: Exception | None = None) -> None:
        self.name, self.jobs, self.error, self.asked = name, jobs, error, 0

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return [Task(self.name, f"{self.name}:{q}", query=q) for q in cfg.search.queries]

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        self.asked += 1
        if self.error:
            raise self.error
        if self.jobs:
            yield [JobStub(source=self.name, url=f"https://{self.name}.test/{task.query}/{i}",
                           title=f"Job {i}", company=f"{self.name} {i}") for i in range(min(self.jobs, task.limit))]  # fmt: skip


class FakeAts(Fake):
    kind = "ats"

    def tasks(self, cfg: SearchConfig) -> list[Task]:
        return []


def _cfg(*enabled: str, companies: tuple[str, ...] = ()) -> SearchConfig:
    return SearchConfig.model_validate({
        "search": {"queries": ["python"]},
        "sources": {"enabled": list(enabled), "companies": list(companies)},
    })  # fmt: skip


def _discover(db: sessionmaker[Session], cfg: SearchConfig, reg: dict[str, Source]) -> None:
    async def go() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(404))
        ) as c:
            await discover(db, cfg, current_run(db, new=True), Http(c, attempts=1), reg)

    asyncio.run(go())


def _row(status: str = "", **kw: object) -> SourceHealth:
    base: dict[str, object] = {"key": "x", "via": "run", "jobs": 0, "error": None,
                               "zero_streak": 0, "ever_found": False}  # fmt: skip
    return SourceHealth(**{**base, **kw})


@pytest.mark.parametrize(
    ("row", "want"),
    [
        (_row(jobs=12), "ok"),
        (_row(error="HTTP 500"), "broken"),
        (_row(jobs=3, error="HTTP 500"), "warn"),  # some searches failed, others found jobs
        (_row(), "empty"),  # never found any: a quiet niche source, not broken
        (_row(zero_streak=3), "empty"),
        (_row(zero_streak=3, ever_found=True), "broken"),  # found jobs before, then 3 empty runs
        (_row(zero_streak=2, ever_found=True), "empty"),
    ],
)
def test_status(row: SourceHealth, want: str) -> None:
    assert health.status(row) == want


def test_runs_record_each_source_and_company(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    reg: dict[str, Source] = {
        "good": Fake("good", jobs=2),
        "quiet": Fake("quiet"),
        "down": Fake("down", error=RuntimeError("parse failed")),
        "off": Fake("off", jobs=5),  # not switched on: no row
        "greenhouse": FakeAts("greenhouse", jobs=1),
    }
    cfg = _cfg("good", "quiet", "down", companies=("greenhouse:acme", "madeup:thing"))
    _discover(db, cfg, reg)
    got = health.summary(db)
    assert {k: v["status"] for k, v in got.items()} == {
        "good": "ok", "quiet": "empty", "down": "broken",
        "company:greenhouse:acme": "ok", "company:madeup:thing": "broken",
    }  # fmt: skip
    assert "parse failed" in str(got["down"]["error"]) and "no known ATS" in str(
        got["company:madeup:thing"]["error"]
    )

    reg["good"] = Fake("good")  # the site changed: it silently returns nothing
    for n in (1, 2, 3):
        _discover(db, cfg, reg)
        assert health.summary(db)["good"]["status"] == ("broken" if n == 3 else "empty")
    reg["good"] = Fake("good", jobs=1)  # fixed: one good run clears it
    _discover(db, cfg, reg)
    assert (
        health.summary(db)["good"]["status"] == "ok"
        and health.summary(db)["good"]["zero_streak"] == 0
    )


def test_check_probes_caches_for_an_hour_and_keeps_runs_going(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    reg: dict[str, Source] = {"good": Fake("good", jobs=9), "down": Fake("down", error=TimeoutError()),
                              "greenhouse": FakeAts("greenhouse", jobs=1)}  # fmt: skip
    cfg = _cfg("good", "down", companies=("greenhouse:acme",))
    assert health.wanted(cfg, reg) == ["down", "good", "company:greenhouse:acme"]

    def check(**kw: object) -> dict[str, health.Result]:
        async def go() -> dict[str, health.Result]:
            async with httpx.AsyncClient() as c:
                return await health.check(db, Http(c, attempts=1), reg, cfg, **kw)  # type: ignore[arg-type]

        return asyncio.run(go())

    first = check()
    assert first["good"].jobs == health.PROBE_LIMIT  # one small page, not a full search
    assert first["down"].error and "no answer" in first["down"].error
    assert first["company:greenhouse:acme"].jobs == 1
    assert check() == {}  # all checked within the hour
    assert set(check(force=True)) == {"down", "good", "company:greenhouse:acme"}
    empty = SearchConfig.model_validate({"sources": {"enabled": ["good"]}})
    got = asyncio.run(health.probe(Http(httpx.AsyncClient()), reg, empty, "good"))
    assert got.error and "nothing to search" in got.error

    # a probe never adds to the empty-run streak, and runs keep their own count
    health.record(db, {"good": health.Result()}, "check")
    assert health.summary(db)["good"]["zero_streak"] == 0
    health.record(db, {"good": health.Result()}, "run", now=utcnow() + timedelta(minutes=1))
    assert health.summary(db)["good"]["zero_streak"] == 1


def test_api(client: TestClient) -> None:  # noqa: F811
    assert client.get("/api/sources/health").json() == {}
    assert (
        client.post("/api/sources/check", json={}, headers=SAME_ORIGIN).json() == {}
    )  # nothing on
    health.record(client.app.state.db, {"remotive": health.Result(jobs=4)}, "run")  # type: ignore[attr-defined]
    got = client.get("/api/sources/health").json()["remotive"]
    assert (got["status"], got["jobs"], got["via"]) == ("ok", 4, "run") and got["at"].endswith("Z")


def test_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[object] = []

    async def fake(
        db: object, settings: object, keys: object = None, force: bool = False, vault: object = None
    ) -> dict[str, object]:
        asked.append((keys, force))
        return {"remotive": {"status": "ok", "jobs": 3, "error": None},
                "company:lever:gone": {"status": "broken", "jobs": 0, "error": "HTTP 404"}}  # fmt: skip

    monkeypatch.setenv("LINKIT_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(pipeline, "check_sources", fake)
    from linkit_all.core.config import get_settings

    get_settings.cache_clear()
    try:
        out = CliRunner().invoke(cli, ["source-check", "remotive", "--force"])
    finally:
        get_settings.cache_clear()
    assert out.exit_code == 1  # something is broken
    assert (
        "[ok] remotive (3 jobs)" in out.output
        and "[BROKEN] lever:gone (0 jobs): HTTP 404" in out.output
    )
    assert asked == [(["remotive"], True)]


def test_migration_adds_and_drops_the_table(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "old.db")
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "d9a7c1e3f568")
        assert "source_health" not in inspect(conn).get_table_names()
        command.upgrade(cfg, "e1b8d2f4a679")
        assert "source_health" in inspect(conn).get_table_names()
        command.downgrade(cfg, "d9a7c1e3f568")
        assert "source_health" not in inspect(conn).get_table_names()
