"""Paired phones (CLAUDE.md §7 Phone, docs/phone.md).

Settings > Phone on the PC makes a one-time code (5 minutes), shown as a QR code holding the
tailnet address. The phone trades it for a long-lived token kept in an HttpOnly, Secure,
SameSite=Strict cookie; only the token's SHA-256 is stored. security.LocalOnly checks that
cookie on every remote request and keeps phones off the PC-only routes.
"""

import hashlib
import hmac
import json
import re
import secrets
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import segno
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.api.security import COOKIE_MAX_AGE
from linkit_all.api.security import DEVICE_COOKIE as COOKIE
from linkit_all.core.config import Settings
from linkit_all.core.models import Device, PushSubscription, utcnow

CODE_TTL = 300.0  # seconds
MAX_FAILURES = 5  # wrong codes per minute; then 429 and the pending code is dropped
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")

router = APIRouter(prefix="/api/phone")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Pairing:
    """The one pending pairing code, in memory only: a restart cancels it."""

    code: str = ""
    expires: float = 0.0
    failures: deque[float] = field(default_factory=deque)

    def new(self, now: float) -> str:
        self.code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        self.expires = now + CODE_TTL
        return self.code

    def claim(self, code: str, now: float) -> bool:
        while self.failures and now - self.failures[0] > 60:
            self.failures.popleft()
        if len(self.failures) >= MAX_FAILURES:
            raise HTTPException(429, "Too many wrong codes: wait a minute, then make a new one")
        given = code.strip().upper().replace("-", "").encode()
        if self.code and now < self.expires and hmac.compare_digest(given, self.code.encode()):
            self.code = ""  # one time only
            return True
        self.failures.append(now)
        if len(self.failures) >= MAX_FAILURES:
            self.code = ""
        return False


def device_id(db: sessionmaker[Session], token: str) -> int | None:
    """The paired, not revoked phone holding this token; touches last_seen once a minute."""
    with db() as s:
        dev = s.scalar(
            select(Device).where(Device.token_hash == token_hash(token), Device.revoked.is_(False))
        )
        if dev is None:
            return None
        now = utcnow()
        if now - dev.last_seen > timedelta(minutes=1):
            dev.last_seen = now
            s.commit()
        return dev.id


# --- remote access switch, kept in the data folder (env LINKIT_REMOTE_* still works) ------


def _remote_file(settings: Settings) -> Path:
    return settings.data_dir / "phone.json"


def load_remote(settings: Settings) -> None:
    """Apply the Phone page's saved choice over the environment defaults."""
    path = _remote_file(settings)
    try:
        saved = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return
    settings.remote_enabled = bool(saved.get("enabled"))
    settings.remote_hosts = [h for h in saved.get("hosts", []) if isinstance(h, str)]


def clean_host(text: str) -> str:
    """`https://pc.tail1234.ts.net/` -> `pc.tail1234.ts.net`; "" when it is no hostname."""
    text = text.strip().lower()
    host = urlparse(text if "://" in text else f"//{text}").hostname or ""
    return host if HOST_RE.match(host) else ""


def detect_host() -> str:
    """The PC's tailnet name from `tailscale status`, or "" (not installed, logged out)."""
    exe = shutil.which("tailscale")
    if not exe:
        return ""
    try:
        out = subprocess.run(  # noqa: S603 (tailscale from PATH, fixed args)
            [exe, "status", "--json"], capture_output=True, timeout=3, check=True
        ).stdout
        name = json.loads(out).get("Self", {}).get("DNSName", "")
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
        return ""
    return clean_host(str(name).rstrip("."))


# --- routes ----------------------------------------------------------------------------


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _db(request: Request) -> sessionmaker[Session]:
    db: sessionmaker[Session] = request.app.state.db
    return db


def _pairing(request: Request) -> Pairing:
    state = request.app.state
    if not hasattr(state, "pairing"):
        state.pairing = Pairing()
    pairing: Pairing = state.pairing
    return pairing


def this_device(request: Request) -> int | None:
    """Set by security.LocalOnly on remote requests; None on the PC itself."""
    return getattr(request.state, "device", None)


def _iso(d: datetime) -> str:
    return d.isoformat() + "Z"


@router.get("")
def status(request: Request) -> dict[str, Any]:
    settings = _settings(request)
    host = settings.remote_hosts[0] if settings.remote_hosts else ""
    out: dict[str, Any] = {
        "enabled": settings.remote_enabled,
        "host": host,
        "address": f"https://{host}/" if host else "",
        "this_device": this_device(request),
    }
    if out["this_device"] is None:  # the PC: its list of phones and a suggested address
        with _db(request)() as s:
            rows = s.scalars(select(Device).where(Device.revoked.is_(False)).order_by(Device.id))
            out["devices"] = [
                {"id": d.id, "name": d.name, "created": _iso(d.created),
                 "last_seen": _iso(d.last_seen)}
                for d in rows
            ]  # fmt: skip
        out["detected_host"] = "" if host else detect_host()
    return out


class RemoteChoice(BaseModel):
    enabled: bool
    host: str = ""


@router.put("/remote")
def set_remote(request: Request, body: RemoteChoice) -> dict[str, Any]:
    settings = _settings(request)
    host = clean_host(body.host) if body.host else ""
    if body.host and not host:
        raise HTTPException(422, "Paste the address tailscale serve printed: pc.tail1234.ts.net")
    if body.enabled and not host:
        raise HTTPException(422, "Add the PC's tailnet address first")
    path = _remote_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled": body.enabled, "hosts": [host] if host else []}), "utf-8")
    load_remote(settings)
    if not body.enabled:
        _pairing(request).code = ""
    return status(request)


@router.post("/pair")
def pair(request: Request) -> dict[str, Any]:
    """A new one-time code; the QR code opens the phone app's pairing page with it."""
    settings = _settings(request)
    if not (settings.remote_enabled and settings.remote_hosts):
        raise HTTPException(409, "Turn on phone access and add the PC's address first")
    code = _pairing(request).new(time.monotonic())
    # the code rides in the fragment: browsers never send it, so no proxy or log sees it
    url = f"https://{settings.remote_hosts[0]}/pair#{code}"
    qr = segno.make(url, error="m").png_data_uri(scale=6, border=2)
    return {"code": code, "url": url, "qr": qr, "expires_in": int(CODE_TTL)}


class Claim(BaseModel):
    code: str = Field(max_length=32)
    name: str = Field("", max_length=80)


@router.post("/claim")
def claim(request: Request, body: Claim, response: Response) -> dict[str, Any]:
    if not _pairing(request).claim(body.code, time.monotonic()):
        raise HTTPException(401, "That code is wrong or expired: make a new one on the PC")
    token = secrets.token_urlsafe(32)
    with _db(request)() as s:
        dev = Device(name=body.name.strip() or "Phone", token_hash=token_hash(token))
        s.add(dev)
        s.commit()
        dev_id = dev.id
    response.set_cookie(
        COOKIE, token, max_age=COOKIE_MAX_AGE, path="/",
        httponly=True, secure=True, samesite="strict",
    )  # fmt: skip
    return {"id": dev_id}


@router.delete("/devices/{device_id}", status_code=204)
def revoke(request: Request, device_id: int) -> None:
    with _db(request)() as s:
        dev = s.get(Device, device_id)
        if dev is None:
            raise HTTPException(404, "No such phone")
        dev.revoked = True
        s.execute(delete(PushSubscription).where(PushSubscription.device_id == device_id))
        s.commit()
    request.app.state.bus.revoke_threadsafe(device_id)  # and its open live view
