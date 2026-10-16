"""Vault: AES-GCM secrets, Argon2id key, keyring cache. Cheap KDF params keep tests fast."""

from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.apply.vault import (
    SERVICE,
    Vault,
    VaultError,
    VaultLocked,
    WrongPassphrase,
    vault_for,
)
from linkit_all.core.config import Settings
from linkit_all.core.db import init_db
from linkit_all.core.models import VaultRow

CHEAP = {"time_cost": 1, "memory_cost": 8, "parallelism": 1}
PASS = "correct horse battery"  # noqa: S105
SECRET = "s3cr3t-Pa55w0rd!-unique-marker"  # noqa: S105


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.store:
            raise PasswordDeleteError("not found")
        del self.store[(service, username)]


class BrokenKeyring(MemoryKeyring):
    def set_password(self, service: str, username: str, password: str) -> None:
        raise RuntimeError("no backend")

    def get_password(self, service: str, username: str) -> str | None:
        raise RuntimeError("no backend")

    def delete_password(self, service: str, username: str) -> None:
        raise RuntimeError("no backend")


@pytest.fixture(autouse=True)
def mem_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.fixture
def db(tmp_path: Path) -> sessionmaker[Session]:
    return init_db(tmp_path / "linkit.db")


@pytest.fixture
def vault(db: sessionmaker[Session]) -> Vault:
    v = Vault(db, "test-key", kdf=CHEAP)
    v.create(PASS)
    v.unlock(PASS)
    return v


def test_create_unlock_wrong_passphrase(db: sessionmaker[Session]) -> None:
    v = Vault(db, "k", kdf=CHEAP)
    assert not v.initialized()
    with pytest.raises(ValueError):
        v.create("short")
    v.create(PASS)
    assert v.initialized()
    assert not v.unlocked()
    with pytest.raises(VaultError):
        v.create(PASS)  # already exists
    with pytest.raises(WrongPassphrase):
        v.unlock("not the passphrase")
    assert not v.unlocked()
    v.unlock(PASS)
    assert v.unlocked()


def test_verify_checks_passphrase_without_changing_state(db: sessionmaker[Session]) -> None:
    v = Vault(db, "k", kdf=CHEAP)
    v.create(PASS)
    assert v.verify(PASS) and not v.verify("not the passphrase")
    assert not v.unlocked()


def test_unlock_before_create_raises(db: sessionmaker[Session]) -> None:
    with pytest.raises(VaultError):
        Vault(db, "k", kdf=CHEAP).unlock(PASS)


def test_put_get_roundtrip_and_upsert(vault: Vault) -> None:
    eid = vault.put("account", "boards.greenhouse.io", "me@x.com", SECRET, {"note": "n"})
    assert vault.get(eid) == SECRET
    # same (kind, site, username) -> same row, new secret, meta kept when not passed
    assert vault.put("account", "boards.greenhouse.io", "me@x.com", "new-secret") == eid
    assert vault.get(eid) == "new-secret"
    assert vault.find("account", "boards.greenhouse.io")[0].meta == {"note": "n"}
    other = vault.put("account", "boards.greenhouse.io", "other@x.com", "x")
    assert other != eid
    assert len(vault.entries()) == 2
    assert [e.username for e in vault.find("account", "boards.greenhouse.io")] == [
        "me@x.com",
        "other@x.com",
    ]
    assert vault.find("imap", "boards.greenhouse.io") == []
    assert not hasattr(vault.entries()[0], "secret")
    with pytest.raises(KeyError):
        vault.get(999)
    vault.delete(eid)
    vault.delete(eid)  # idempotent
    assert [e.id for e in vault.entries()] == [other]


def test_ciphertext_does_not_contain_plaintext(
    vault: Vault, db: sessionmaker[Session], tmp_path: Path
) -> None:
    vault.put("account", "site", "u", SECRET)
    with db() as s:
        row = s.scalars(select(VaultRow)).one()
        assert SECRET.encode() not in row.ciphertext
        assert len(row.nonce) == 12
    for f in tmp_path.glob("linkit.db*"):  # also WAL
        assert SECRET.encode() not in f.read_bytes()
    # fresh nonce per encryption
    vault.put("account", "site", "u", SECRET)
    with db() as s:
        assert s.scalars(select(VaultRow)).one().nonce != row.nonce


def test_aad_binds_row(vault: Vault, db: sessionmaker[Session]) -> None:
    eid = vault.put("account", "site-a", "u", SECRET)
    with db.begin() as s:
        s.execute(update(VaultRow).where(VaultRow.id == eid).values(site="site-b"))
    with pytest.raises(VaultError) as e:
        vault.get(eid)
    assert SECRET not in str(e.value)


def test_lock_forgets_key_and_keyring(vault: Vault, mem_keyring: MemoryKeyring) -> None:
    eid = vault.put("account", "s", "u", SECRET)
    assert (SERVICE, "test-key") in mem_keyring.store
    vault.lock()
    assert not vault.unlocked()
    assert mem_keyring.store == {}
    with pytest.raises(VaultLocked):
        vault.get(eid)
    assert vault.unlock_from_keyring() is False


def test_unlock_from_keyring_after_restart(
    vault: Vault, db: sessionmaker[Session], mem_keyring: MemoryKeyring
) -> None:
    eid = vault.put("account", "s", "u", SECRET)
    restarted = Vault(db, "test-key", kdf=CHEAP)
    assert not restarted.unlocked()
    assert restarted.unlock_from_keyring() is True
    assert restarted.get(eid) == SECRET
    # remember=False leaves nothing behind
    restarted.lock()
    restarted.unlock(PASS, remember=False)
    assert mem_keyring.store == {}
    assert Vault(db, "test-key", kdf=CHEAP).unlock_from_keyring() is False


def test_stale_or_garbage_keyring_entry_is_dropped(
    db: sessionmaker[Session], mem_keyring: MemoryKeyring
) -> None:
    v = Vault(db, "k", kdf=CHEAP)
    assert v.unlock_from_keyring() is False  # no vault yet
    v.create(PASS)
    for junk in ("%%%not-base64%%%", "AAAA"):
        mem_keyring.store[(SERVICE, "k")] = junk
        assert v.unlock_from_keyring() is False
        assert not v.unlocked()
        assert mem_keyring.store == {}


def test_export_needs_right_passphrase(vault: Vault) -> None:
    vault.put("account", "s", "u", SECRET, {"a": 1})
    assert vault.unlocked()
    with pytest.raises(WrongPassphrase):
        vault.export("wrong passphrase")
    (row,) = vault.export(PASS)
    assert row["secret"] == SECRET
    assert (row["kind"], row["site"], row["username"], row["meta"]) == (
        "account",
        "s",
        "u",
        {"a": 1},
    )


def test_operations_raise_when_locked(db: sessionmaker[Session]) -> None:
    v = Vault(db, "k", kdf=CHEAP)
    v.create(PASS)
    for call in (
        lambda: v.put("a", "b", "c", "d"),
        lambda: v.get(1),
        lambda: v.find("a", "b"),
        lambda: v.entries(),
        lambda: v.delete(1),
    ):
        with pytest.raises(VaultLocked):
            call()


def test_broken_keyring_does_not_crash(db: sessionmaker[Session]) -> None:
    keyring.set_keyring(BrokenKeyring())
    v = Vault(db, "k", kdf=CHEAP)
    v.create(PASS)
    v.unlock(PASS)  # remember fails quietly
    assert v.unlocked()
    eid = v.put("account", "s", "u", SECRET)
    assert v.get(eid) == SECRET
    assert Vault(db, "k", kdf=CHEAP).unlock_from_keyring() is False
    v.lock()
    assert not v.unlocked()


def test_vault_for_key_is_per_data_dir(db: sessionmaker[Session], tmp_path: Path) -> None:
    a = vault_for(Settings(data_dir=tmp_path / "a"), db)
    b = vault_for(Settings(data_dir=tmp_path / "b"), db)
    assert a._key_id != b._key_id
    assert a._key_id == vault_for(Settings(data_dir=tmp_path / "a"), db)._key_id
