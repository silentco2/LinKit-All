import asyncio
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import keyring
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_vault import MemoryKeyring

from linkit_all.api.app import create_app
from linkit_all.api.runner import RunBusy
from linkit_all.core.config import Settings
from linkit_all.core.db import make_engine
from linkit_all.core.scheduler import (
    apply_schedule,
    make_scheduler,
    next_runs,
    register_runner,
    scheduled_run,
)
from linkit_all.core.search import ScheduleSection, SearchConfig
from linkit_all.pipeline import STAGES


def cfg(**schedule: Any) -> SearchConfig:
    return SearchConfig(schedule=ScheduleSection(enabled=True, **schedule))


@pytest.mark.parametrize("bad", ["9:00", "24:00", "09:60", "0900", "ab:cd", ""])
def test_bad_times_rejected(bad: str) -> None:
    with pytest.raises(ValidationError):
        ScheduleSection(times=["09:00", bad])


def test_schedule_validation() -> None:
    s = ScheduleSection(days=[4, 0, 0], times=["17:30", "09:00", "09:00"])
    assert s.days == [0, 4] and s.times == ["09:00", "17:30"]  # sorted, deduped
    assert ScheduleSection().enabled is False and SearchConfig().schedule.times == ["09:00"]
    for bad in (
        {"days": [7]},
        {"days": []},
        {"times": []},
        {"times": [f"0{i}:00" for i in range(7)]},
    ):
        with pytest.raises(ValidationError):
            ScheduleSection(**bad)


def test_apply_schedule_creates_triggers() -> None:
    async def main() -> None:
        sched = make_scheduler(timezone=UTC)
        sched.start()
        apply_schedule(sched, cfg(days=[0, 2], times=["09:00", "17:30"]))
        assert sorted(j.id for j in sched.get_jobs()) == ["run-0900", "run-1730"]
        runs = next_runs(sched, 3)
        assert len(runs) == 3 and runs == sorted(runs) and runs[0] > datetime.now(UTC)
        assert all(t.weekday() in (0, 2) and (t.hour, t.minute) in ((9, 0), (17, 30)) for t in runs)

        apply_schedule(sched, cfg(days=[0, 2], times=["08:15"]))  # replaces, no leftovers
        assert [j.id for j in sched.get_jobs()] == ["run-0815"]
        assert all((t.hour, t.minute) == (8, 15) for t in next_runs(sched))

        apply_schedule(sched, SearchConfig())  # disabled
        assert sched.get_jobs() == [] and next_runs(sched) == []
        sched.shutdown(wait=False)

    asyncio.run(main())


def test_jobs_survive_restart(tmp_path: Path) -> None:
    engine = make_engine(tmp_path / "app.db")
    want = cfg(times=["06:00"], new_run=False)

    async def main() -> None:
        first = make_scheduler(engine, UTC)
        first.start()
        apply_schedule(first, want)
        fire = first.get_job("run-0600").next_run_time  # type: ignore[union-attr]
        first.shutdown(wait=False)

        second = make_scheduler(engine, UTC)
        second.start()
        job = second.get_job("run-0600")
        assert job is not None and job.args == (False,) and job.next_run_time == fire
        apply_schedule(second, want)  # same config: left untouched
        assert second.get_job("run-0600").next_run_time == fire  # type: ignore[union-attr]
        second.shutdown(wait=False)

    asyncio.run(main())


class FakeRunner:
    def __init__(self, busy: bool) -> None:
        self.busy, self.calls = busy, []  # type: ignore[var-annotated]

    def start(self, stages: list[str], new: bool = False) -> None:
        if self.busy:
            raise RunBusy("a run is already in progress")
        self.calls.append((stages, new))


def test_scheduled_run_starts_or_skips() -> None:
    try:
        busy = FakeRunner(busy=True)
        register_runner(busy)  # type: ignore[arg-type]
        assert asyncio.run(scheduled_run(True)) is False  # skipped quietly
        free = FakeRunner(busy=False)
        register_runner(free)  # type: ignore[arg-type]
        assert asyncio.run(scheduled_run(False)) is True
        assert free.calls == [(list(STAGES), False)]
        register_runner(None)
        assert asyncio.run(scheduled_run(True)) is False  # app not ready: no crash
    finally:
        register_runner(None)


def test_scheduled_run_skips_while_app_browser_open() -> None:
    class OpenBrowser:
        is_open = True

    runner = FakeRunner(busy=False)
    try:
        register_runner(runner, OpenBrowser())  # type: ignore[arg-type]
        assert asyncio.run(scheduled_run(True)) is False and runner.calls == []
        OpenBrowser.is_open = False
        assert asyncio.run(scheduled_run(True)) is True
    finally:
        register_runner(None)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    app = create_app(Settings(data_dir=tmp_path / "data"))
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c
    keyring.set_keyring(previous)


def test_schedule_api(client: TestClient) -> None:
    assert client.get("/api/schedule").json() == {"enabled": False, "next_runs": []}
    assert client.get("/api/status").json()["next_run"] is None

    body = SearchConfig().model_dump()
    body["schedule"] = {
        "enabled": True,
        "days": [0, 1, 2, 3, 4],
        "times": ["09:00"],
        "new_run": True,
    }
    assert client.put("/api/search", json=body).status_code == 200
    got = client.get("/api/schedule").json()
    assert got["enabled"] is True and len(got["next_runs"]) == 3
    assert client.get("/api/status").json()["next_run"] == got["next_runs"][0]

    body["schedule"]["times"] = ["25:00"]
    assert client.put("/api/search", json=body).status_code == 422
    assert client.get("/api/schedule").json()["enabled"] is True  # bad save changed nothing

    body["schedule"] = {"enabled": False, "days": [0], "times": ["09:00"], "new_run": True}
    client.put("/api/search", json=body)
    assert client.get("/api/schedule").json() == {"enabled": False, "next_runs": []}
