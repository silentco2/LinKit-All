"""Site accounts: password rules and the vault records. Cheap KDF keeps tests fast."""

import string
from collections.abc import Iterator
from pathlib import Path

import keyring
import pytest
from sqlalchemy.orm import Session, sessionmaker
from test_vault import CHEAP, PASS, MemoryKeyring

from linkit_all.apply.accounts import (
    KIND,
    PasswordRules,
    create_account,
    find_account,
    generate_password,
    mark_active,
)
from linkit_all.apply.vault import Vault, VaultLocked
from linkit_all.core.db import init_db


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


def test_default_rules_always_satisfied() -> None:
    rules = PasswordRules()
    seen = set()
    for _ in range(300):
        p = generate_password(rules)
        seen.add(p)
        assert rules.min_len <= len(p) <= rules.max_len
        assert any(c in string.ascii_uppercase for c in p)
        assert any(c in string.ascii_lowercase for c in p)
        assert any(c in string.digits for c in p)
        assert any(c in rules.symbols for c in p)
        assert set(p) <= set(string.ascii_letters + string.digits + rules.symbols)
    assert len(seen) == 300


def test_custom_rules_length_forbidden_and_no_symbols() -> None:
    rules = PasswordRules(min_len=8, max_len=10, symbols="", need_symbol=False, forbidden="0Ol1I")
    for _ in range(300):
        p = generate_password(rules)
        assert 8 <= len(p) <= 10
        assert not set(p) & set("0Ol1I")
        assert set(p) <= set(string.ascii_letters + string.digits)
    tight = PasswordRules(min_len=30, max_len=40, symbols="!@")
    assert all(30 <= len(generate_password(tight)) <= 40 for _ in range(50))
    short = PasswordRules(min_len=4, max_len=6)
    assert all(4 <= len(generate_password(short)) <= 6 for _ in range(50))


def test_impossible_rules_raise() -> None:
    with pytest.raises(ValueError):
        generate_password(PasswordRules(symbols="", need_symbol=True))
    with pytest.raises(ValueError):
        generate_password(PasswordRules(min_len=2, max_len=3))


def test_create_find_mark_active(vault: Vault) -> None:
    assert find_account(vault, "workday", "acme") is None
    acct = create_account(vault, "workday", "acme", "jane@example.com", PasswordRules())
    assert acct.status == "pending_signup"
    [entry] = vault.find(KIND, "workday:acme")
    assert entry.username == "jane@example.com"
    assert entry.meta["status"] == "pending_signup" and entry.meta["created_at"]
    assert vault.get(entry.id) == acct.password

    found = find_account(vault, "workday", "acme")
    assert (
        found is not None and found.password == acct.password and found.status == "pending_signup"
    )

    active = mark_active(vault, acct, "workday", "acme")
    assert active.status == "active"
    [entry] = vault.find(KIND, "workday:acme")
    assert entry.meta["status"] == "active" and entry.meta["created_at"]
    assert vault.get(entry.id) == acct.password
    assert find_account(vault, "workday", "other") is None


def test_locked_vault_raises(db: sessionmaker[Session]) -> None:
    v = Vault(db, "k", kdf=CHEAP)
    v.create(PASS)
    with pytest.raises(VaultLocked):
        find_account(v, "workday", "acme")
    with pytest.raises(VaultLocked):
        create_account(v, "workday", "acme", "a@b.c", PasswordRules())
