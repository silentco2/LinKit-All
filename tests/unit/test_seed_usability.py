"""The usability-study seeder fills a data dir the app reads correctly (scripts/seed_usability.py)."""

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from fastapi.testclient import TestClient
from test_api import mem_keyring  # noqa: F401  (autouse fixture: never touch the real keyring)
from test_vault import CHEAP

from linkit_all.api.app import create_app
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings

SCRIPT = Path(__file__).parents[2] / "scripts" / "seed_usability.py"


def load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_usability", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[tuple[TestClient, dict[str, int]]]:
    data = tmp_path / "data"
    states = load_script().seed(data)
    app = create_app(Settings(data_dir=data))
    app.state.vault = Vault(app.state.db, "seed-test", CHEAP)
    with TestClient(app, base_url="http://127.0.0.1:8765") as c:
        yield c, states


def test_seeded_state_reads_back(seeded: tuple[TestClient, dict[str, int]]) -> None:
    client, states = seeded
    status = client.get("/api/status").json()
    assert status["states"] == states
    assert states["filtered_out"] == 6 and states["awaiting_review"] == 8
    assert states["queued_apply"] == 5 and states["needs_user"] == 5
    assert status["setup"]["required_done"] and status["ai_ready"]
    assert status["actions_open"] == 5 and status["practiced"] == 3

    groups = client.get("/api/actions/groups").json()
    notice = next(g for g in groups if g["label"] == "What is your notice period?")
    assert notice["count"] == 4 and not notice["sensitive"]
    assert any(g["sensitive"] and g["count"] == 1 for g in groups)  # the privacy question

    golive = client.get("/api/golive").json()
    assert golive["eligible"] and len(golive["samples"]) == 3
    assert golive["checklist"]["cv_approved"]
    shot = client.get(golive["samples"][0]["screenshots"][0])
    assert shot.status_code == 200 and shot.content.startswith(b"\x89PNG")

    rows = client.get("/api/jobs", params={"state": "filtered_out"}).json()
    codes = {r["reason_code"] for r in rows}
    assert {"title_excluded", "location", "blacklist", "too_old"} <= codes
    assert any(r["reason"] == 'Title contains "intern"' for r in rows)
    assert client.get("/api/runs").json()["recent"][0]["status"] == "done"
    assert client.get("/api/profile/cv/segments").json()  # the CV went through the upload path


def test_arabic_seed_and_real_dir_refused(tmp_path: Path) -> None:
    mod = load_script()
    assert sum(mod.seed(tmp_path / "ar", "ar").values()) == 67
    real = Path(mod.user_data_dir("linkit-all", appauthor=False))
    assert mod.main(["--data-dir", str(real)]) == 2
    assert mod.main(["--data-dir", str(tmp_path / "ar")]) == 1  # not empty, no --reset
