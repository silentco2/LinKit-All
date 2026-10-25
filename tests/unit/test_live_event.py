"""The live browser frame arrives as a per-job `live_shot` event on the EventBus."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_api import BASE, client  # noqa: F401  (fixture)
from test_apply_vault import NoAI

from linkit_all.api import runner as api_runner
from linkit_all.api.events import EventBus
from linkit_all.apply import browser as browser_module
from linkit_all.apply import runner
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.search import SearchConfig


class Page:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def screenshot(self, **_: Any) -> bytes:
        if self.fail:
            raise RuntimeError("mid-navigation")
        return b"\xff\xd8jpeg"


def _frames(tmp_path: Path, page: Page) -> int:
    out = tmp_path / "live" / "current.jpg"
    calls: list[int] = []

    async def go() -> None:
        task = asyncio.create_task(
            browser_module.live_frames(page, out, every=0.01, on_frame=lambda: calls.append(1))  # type: ignore[arg-type]
        )
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(go())
    return len(calls)


def test_on_frame_fires_for_each_written_frame_only(tmp_path: Path) -> None:
    assert _frames(tmp_path, Page()) >= 2
    assert _frames(tmp_path, Page(fail=True)) == 0  # nothing written, nothing announced


def test_applier_announces_job_id_title_company_and_a_new_version(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    events: list[dict[str, Any]] = []
    applier = runner.Applier(
        db,
        settings,
        SearchConfig(),
        NoAI(),
        None,
        publish=events.append,  # type: ignore[arg-type]
    )
    applier._announce_frame(7, "Dev", "Acme")
    [e] = events
    assert (e["type"], e["job_id"], e["title"], e["company"]) == ("live_shot", 7, "Dev", "Acme")
    assert e["url"] == f"/api/live/screenshot?v={e['version']}"
    assert set(e) == {"type", "job_id", "title", "company", "version", "url"}  # no CV text/answers
    # no publisher (CLI): silently nothing
    runner.Applier(db, settings, SearchConfig(), NoAI(), None)._announce_frame(1, "a", "b")  # type: ignore[arg-type]


def test_bus_keeps_only_the_newest_live_shot_out_of_the_log() -> None:
    bus = EventBus()
    bus.publish({"type": "log", "message": "hi"})
    bus.publish({"type": "live_shot", "job_id": 1})
    bus.publish({"type": "live_shot", "job_id": 2})
    assert [e["type"] for e in bus.recent] == ["log"]
    assert bus.last_shot is not None and bus.last_shot["job_id"] == 2


def test_run_end_forgets_the_last_shot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = init_db(tmp_path / "x.db")
    bus = EventBus()
    seen: list[Any] = []

    async def fake_stage(*args: Any) -> dict[str, Any]:
        seen.append(args[6])
        args[6]({"type": "live_shot", "job_id": 3})
        return {}

    monkeypatch.setattr(api_runner, "run_stage", fake_stage)

    async def go() -> None:
        r = api_runner.PipelineRunner(db, Settings(data_dir=tmp_path), bus)
        r.start(["apply"])
        assert r._task is not None
        await r._task

    asyncio.run(go())
    assert seen == [bus.publish] and bus.last_shot is None


def test_new_viewer_gets_the_latest_shot(client: TestClient) -> None:  # noqa: F811
    client.app.state.bus.publish({"type": "live_shot", "job_id": 5, "url": "/x"})  # type: ignore[attr-defined]
    with client.websocket_connect("ws://127.0.0.1:8765/api/events", headers={"origin": BASE}) as ws:
        first = ws.receive_json()
        while first["type"] != "live_shot":  # replayed log lines come first
            first = ws.receive_json()
        assert first["job_id"] == 5


def test_screenshot_endpoint_serves_only_from_the_data_dir(
    client: TestClient,  # noqa: F811
    tmp_path: Path,
) -> None:
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"x")
    shot = browser_module.live_shot_path(client.app.state.settings)  # type: ignore[attr-defined]
    shot.parent.mkdir(parents=True)
    shot.symlink_to(outside)
    assert client.get("/api/live/screenshot").status_code == 404
    shot.unlink()
    shot.write_bytes(b"jpeg")
    assert client.get("/api/live/screenshot?v=1").status_code == 200
