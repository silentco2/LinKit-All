"""Local secrets vault: AES-GCM per secret, key from a master passphrase via Argon2id.

The derived key lives in memory while unlocked and, if the user asks, in the OS keyring so a
restart can unlock without retyping. Nothing here logs or raises with passphrases, keys or
secrets (CLAUDE.md §2, §6).
"""

import base64
import hashlib
import os
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import keyring
from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.config import Settings
from linkit_all.core.models import VaultMeta, VaultRow, utcnow

SERVICE = "linkit-all"
MIN_PASSPHRASE = 8
# OWASP-reasonable Argon2id; stored per vault, so these can change later without breaking old ones.
DEFAULT_KDF = {"time_cost": 3, "memory_cost": 64 * 1024, "parallelism": 4}  # memory in KiB
_CHECK_PLAINTEXT = b"linkit-vault-check-v1"
_CHECK_AAD = b"vault-check"


class VaultError(Exception):
    pass


class VaultLocked(VaultError):
    pass


class WrongPassphrase(VaultError):
    pass


@dataclass(frozen=True)
class VaultEntry:
    """A vault entry without its secret."""

    id: int
    kind: str
    site: str
    username: str
    meta: dict[str, Any]
    created_at: datetime
    updated_at: datetime


def _aad(kind: str, site: str, username: str) -> bytes:
    return f"{kind}\0{site}\0{username}".encode()


def _view(r: VaultRow) -> VaultEntry:
    return VaultEntry(r.id, r.kind, r.site, r.username, r.meta, r.created_at, r.updated_at)


class Vault:
    def __init__(
        self, db: sessionmaker[Session], key_id: str, kdf: dict[str, int] | None = None
    ) -> None:
        self._db = db
        self._key_id = key_id
        self._kdf = dict(kdf or DEFAULT_KDF)  # used by create(); unlock() reads the stored params
        self._key: bytes | None = None

    # -- keyring (best effort: a missing or broken backend means "not remembered") --

    def _keyring_get(self) -> str | None:
        try:
            return keyring.get_password(SERVICE, self._key_id)
        except Exception as e:
            logger.warning("keyring unavailable ({}), vault key not restored", type(e).__name__)
            return None

    def _keyring_set(self, key: bytes) -> None:
        try:
            keyring.set_password(SERVICE, self._key_id, base64.b64encode(key).decode())
        except Exception as e:
            logger.warning("keyring unavailable ({}), vault key not remembered", type(e).__name__)

    def _keyring_delete(self) -> None:
        try:
            keyring.delete_password(SERVICE, self._key_id)
        except Exception as e:  # PasswordDeleteError when nothing was stored is expected
            logger.debug("keyring delete skipped ({})", type(e).__name__)

    # -- key handling --

    @staticmethod
    def _derive(passphrase: str, salt: bytes, kdf: dict[str, Any]) -> bytes:
        return hash_secret_raw(
            secret=unicodedata.normalize("NFKC", passphrase).encode(),
            salt=salt,
            time_cost=int(kdf["time_cost"]),
            memory_cost=int(kdf["memory_cost"]),
            parallelism=int(kdf["parallelism"]),
            hash_len=32,
            type=Type.ID,
        )

    @staticmethod
    def _key_ok(key: bytes, meta: VaultMeta) -> bool:
        try:
            plain = AESGCM(key).decrypt(meta.check_nonce, meta.check_ciphertext, _CHECK_AAD)
        except (InvalidTag, ValueError):
            return False
        return plain == _CHECK_PLAINTEXT

    @staticmethod
    def _meta(s: Session) -> VaultMeta | None:
        return s.scalars(select(VaultMeta)).first()

    def _verified_key(self, passphrase: str) -> bytes:
        with self._db() as s:
            meta = self._meta(s)
            if meta is None:
                raise VaultError("vault is not set up")
            key = self._derive(passphrase, meta.salt, meta.kdf)
            if not self._key_ok(key, meta):
                raise WrongPassphrase("wrong passphrase")
            return key

    def _need_key(self) -> bytes:
        if self._key is None:
            raise VaultLocked("vault is locked")
        return self._key

    # -- lifecycle --

    def initialized(self) -> bool:
        with self._db() as s:
            return self._meta(s) is not None

    def unlocked(self) -> bool:
        return self._key is not None

    def create(self, passphrase: str) -> None:
        if len(passphrase) < MIN_PASSPHRASE:
            raise ValueError(f"passphrase must be at least {MIN_PASSPHRASE} characters")
        with self._db.begin() as s:
            if self._meta(s) is not None:
                raise VaultError("vault already exists")
            salt = os.urandom(16)
            key = self._derive(passphrase, salt, self._kdf)
            nonce = os.urandom(12)
            s.add(
                VaultMeta(
                    salt=salt,
                    kdf=self._kdf,
                    check_nonce=nonce,
                    check_ciphertext=AESGCM(key).encrypt(nonce, _CHECK_PLAINTEXT, _CHECK_AAD),
                )
            )

    def unlock(self, passphrase: str, remember: bool = True) -> None:
        self._key = self._verified_key(passphrase)
        if remember:
            self._keyring_set(self._key)

    def unlock_from_keyring(self) -> bool:
        stored = self._keyring_get()
        if stored is None:
            return False
        try:
            key = base64.b64decode(stored, validate=True)
        except ValueError:
            key = b""
        with self._db() as s:
            meta = self._meta(s)
            ok = meta is not None and len(key) == 32 and self._key_ok(key, meta)
        if not ok:  # stale entry (vault recreated, data dir changed)
            self._keyring_delete()
            return False
        self._key = key
        return True

    def verify(self, passphrase: str) -> bool:
        """True if the passphrase is right. Does not change the locked state."""
        try:
            self._verified_key(passphrase)
        except WrongPassphrase:
            return False
        return True

    def lock(self) -> None:
        self._key = None
        self._keyring_delete()

    # -- secrets --

    def put(
        self, kind: str, site: str, username: str, secret: str, meta: dict[str, Any] | None = None
    ) -> int:
        """Insert or update the entry for (kind, site, username). `meta` is stored in plaintext."""
        key = self._need_key()
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, secret.encode(), _aad(kind, site, username))
        with self._db.begin() as s:
            row = s.scalars(
                select(VaultRow).where(
                    VaultRow.kind == kind, VaultRow.site == site, VaultRow.username == username
                )
            ).first()
            if row is None:
                row = VaultRow(kind=kind, site=site, username=username, nonce=nonce, ciphertext=ct)
                s.add(row)
            row.nonce, row.ciphertext, row.updated_at = nonce, ct, utcnow()
            if meta is not None:
                row.meta = meta
            s.flush()
            return row.id

    @staticmethod
    def _decrypt(key: bytes, r: VaultRow) -> str:
        try:
            plain = AESGCM(key).decrypt(r.nonce, r.ciphertext, _aad(r.kind, r.site, r.username))
        except InvalidTag:
            raise VaultError(f"entry {r.id} failed authentication") from None
        return plain.decode()

    def get(self, entry_id: int) -> str:
        key = self._need_key()
        with self._db() as s:
            row = s.get(VaultRow, entry_id)
            if row is None:
                raise KeyError(entry_id)
            return self._decrypt(key, row)

    def find(self, kind: str, site: str) -> list[VaultEntry]:
        self._need_key()
        with self._db() as s:
            rows = s.scalars(
                select(VaultRow).where(VaultRow.kind == kind, VaultRow.site == site)
            ).all()
            return [_view(r) for r in rows]

    def entries(self) -> list[VaultEntry]:
        self._need_key()
        with self._db() as s:
            return [_view(r) for r in s.scalars(select(VaultRow).order_by(VaultRow.id))]

    def delete(self, entry_id: int) -> None:
        self._need_key()
        with self._db.begin() as s:
            row = s.get(VaultRow, entry_id)
            if row is not None:
                s.delete(row)

    def export(self, passphrase: str) -> list[dict[str, Any]]:
        """Every entry with its secret. Re-checks the passphrase even when already unlocked."""
        key = self._verified_key(passphrase)
        with self._db() as s:
            return [
                {
                    "id": r.id,
                    "kind": r.kind,
                    "site": r.site,
                    "username": r.username,
                    "secret": self._decrypt(key, r),
                    "meta": r.meta,
                    "created_at": r.created_at.isoformat(),
                    "updated_at": r.updated_at.isoformat(),
                }
                for r in s.scalars(select(VaultRow).order_by(VaultRow.id))
            ]


def vault_for(settings: Settings, db: sessionmaker[Session]) -> Vault:
    """A vault whose keyring entry is unique to this data dir."""
    digest = hashlib.sha256(str(settings.data_dir.resolve()).encode()).hexdigest()[:12]
    return Vault(db, f"vault-{digest}")
