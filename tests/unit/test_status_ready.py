from collections.abc import Iterator
from pathlib import Path
from typing import Any

import keyring
import pytest
from fastapi.testclient import TestClient
from test_vault import CHEAP, MemoryKeyring

from linkit_all.api.app import create_app
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings
from linkit_all.core.models import Job, JobState
from linkit_all.core.search import SearchConfig

BASE = "http://127.0.0.1:8765"
SAME_ORIGIN = {"origin": BASE}


@pytest.fixture(autouse=True)
def mem_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    app = create_app(Settings(data_dir=tmp_path / "data"))
    app.state.vault = Vault(app.state.db, "api-test", CHEAP)
    with TestClient(app, base_url=BASE) as c:
        yield c


def add_jobs(client: TestClient) -> None:
    def job(n: int, state: JobState, **kw: Any) -> Job:
        return Job(
            source="t", url=f"https://x/{n}", title="Dev", company=f"C{n}", dedupe_hash=str(n),
            ats="greenhouse", state=state, **kw,
        )  # fmt: skip

    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        s.add_all(
            [
                job(1, JobState.queued_apply),
                job(2, JobState.queued_apply, data={"dry_run_at": "2026-10-29T10:00:00"}),
                job(3, JobState.tailored, data={"dry_run_at": "2026-10-29T10:00:00"}),
                job(4, JobState.applied, data={"dry_run_at": "2026-10-29T10:00:00"}),
                job(5, JobState.scored),  # not in the apply queue
            ]
        )


def set_live(client: TestClient, live: bool) -> None:
    body = SearchConfig.model_validate({"apply": {"live": live}}).model_dump(mode="json")
    assert client.put("/api/search", json=body, headers=SAME_ORIGIN).status_code == 200


def test_practice_mode_excludes_practised_jobs(client: TestClient) -> None:
    add_jobs(client)
    set_live(client, False)
    st = client.get("/api/status").json()
    assert st["ready_to_apply"] == 1  # only the fresh queued job
    assert st["practiced"] == 3  # whatever their state
    assert st["states"]["queued_apply"] == 2  # existing keys unchanged


def test_live_mode_takes_practised_jobs_too(client: TestClient) -> None:
    add_jobs(client)
    set_live(client, True)
    st = client.get("/api/status").json()
    assert st["ready_to_apply"] == 3  # queued x2 + tailored; applied/scored never
    assert st["practiced"] == 3


def test_jobs_the_runner_cannot_handle_are_not_ready(client: TestClient) -> None:
    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        s.add(
            Job(
                source="t",
                url="no-link",
                title="Dev",
                company="Z",
                dedupe_hash="z",
                ats="unknown-ats",
                state=JobState.queued_apply,
            )
        )
    st = client.get("/api/status").json()
    assert st["ready_to_apply"] == 0 and st["practiced"] == 0
