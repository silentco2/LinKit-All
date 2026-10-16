"""The applier uses the server's vault when given one, else unlocks its own from the keyring."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session, sessionmaker
from test_matching import fake_embed
from test_vault import CHEAP, PASS

from linkit_all.api import runner as api_runner
from linkit_all.api.events import EventBus
from linkit_all.apply import runner
from linkit_all.apply.vault import Vault
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.search import SearchConfig
from linkit_all.providers.base import LLMProvider


class NoAI(LLMProvider):
    name = "none"

    def __init__(self) -> None:
        super().__init__("none")

    async def _call(self, prompt: str) -> str:
        raise AssertionError("no AI call expected")


def make_applier(tmp_path: Path, vault: Vault | None = None) -> runner.Applier:
    settings = Settings(data_dir=tmp_path / "data")
    db = init_db(settings.db_path)
    return runner.Applier(db, settings, SearchConfig(), NoAI(), fake_embed, vault)


def test_given_vault_unlocked_without_remember_is_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    applier = make_applier(tmp_path)
    server_vault = Vault(applier.db, "server", kdf=CHEAP)
    server_vault.create(PASS)
    server_vault.unlock(PASS, remember=False)  # nothing in the keyring
    applier._vault = server_vault
    monkeypatch.setattr(runner, "vault_for", lambda *a: pytest.fail("must not build its own"))
    assert applier._unlocked_vault() is server_vault


def test_given_vault_still_locked_means_no_vault(tmp_path: Path) -> None:
    applier = make_applier(tmp_path)
    server_vault = Vault(applier.db, "server", kdf=CHEAP)
    server_vault.create(PASS)
    server_vault.lock()
    applier._vault = server_vault
    assert applier._unlocked_vault() is None


def test_without_vault_falls_back_to_keyring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    applier = make_applier(tmp_path)
    monkeypatch.setattr(runner, "vault_for", lambda *a: Vault(applier.db, "cli", kdf=CHEAP))
    assert applier._unlocked_vault() is None  # no vault yet
    first = Vault(applier.db, "cli", kdf=CHEAP)
    first.create(PASS)
    first.unlock(PASS, remember=True)
    got = applier._unlocked_vault()
    assert got is not None and got.unlocked()


def test_pipeline_runner_hands_its_vault_to_run_stage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db: sessionmaker[Session] = init_db(tmp_path / "x.db")
    vault = Vault(db, "server", kdf=CHEAP)
    seen: list[Any] = []

    async def fake_stage(*args: Any) -> dict[str, Any]:
        seen.append(args[5])
        return {}

    monkeypatch.setattr(api_runner, "run_stage", fake_stage)

    async def go() -> None:
        r = api_runner.PipelineRunner(db, Settings(data_dir=tmp_path), EventBus(), vault)
        r.start(["apply"])
        assert r._task is not None
        await r._task

    asyncio.run(go())
    assert seen == [vault]
