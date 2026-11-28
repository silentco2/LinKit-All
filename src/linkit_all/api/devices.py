"""Paired phones (CLAUDE.md §7 Phone, docs/phone.md).

Home > Remote control on the PC (or `linkit rc`) turns on the tunnel (api/tunnel.py) and makes a
one-time code (5 minutes), shown as a QR code: a linkit-all.github.io/app/ link carrying the PC's
iroh id, its relay and the code. The phone trades the code for a long-lived token, tied to the
phone's own iroh id; only the token's SHA-256 is stored. security.LocalOnly checks the token and
the iroh id on every phone request and keeps phones off the PC-only routes.
"""

import hashlib
import hmac
import json
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import segno
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.config import Settings
from linkit_all.core.models import Device, PushSubscription, utcnow

CODE_TTL = 300.0  # seconds
MAX_FAILURES = 5  # wrong codes per minute; then 429 and the pending code is dropped
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I/L
PHONE_APP = "https://linkit-all.github.io/app/"  # the phone web app, built from this repo

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


def device_id(db: sessionmaker[Session], token: str, peer: str) -> int | None:
    """The paired, not revoked phone with this token and iroh id; touches last_seen once a minute.

    A token copied off the phone is useless from any other device: iroh proves the id."""
    with db() as s:
        dev = s.scalar(
            select(Device).where(Device.token_hash == token_hash(token), Device.revoked.is_(False))
        )
        if dev is None or not peer or not hmac.compare_digest(dev.peer or "", peer):
            return None
        now = utcnow()
        if now - dev.last_seen > timedelta(minutes=1):
            dev.last_seen = now
            s.commit()
        return dev.id


# --- phone access switch, kept in the data folder (env LINKIT_REMOTE_ENABLED still works) ----


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
    relay = saved.get("relay")
    settings.phone_relay = relay if isinstance(relay, str) and relay else None


def save_remote(settings: Settings, enabled: bool, relay: str) -> None:
    """Keep the choice (Home > Remote control, `linkit rc`) and apply it to these settings."""
    path = _remote_file(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"enabled": enabled, "relay": relay}), "utf-8")
    load_remote(settings)


def clean_relay(text: str) -> str:
    """An https relay URL (the user's own iroh relay), or "" when it is not one."""
    url = urlparse(text.strip())
    return url.geturl() if url.scheme == "https" and url.hostname else ""


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


def _tunnel(request: Request) -> Any:
    return request.app.state.tunnel


@router.get("")
def status(request: Request) -> dict[str, Any]:
    settings, tunnel = _settings(request), _tunnel(request)
    out: dict[str, Any] = {
        "enabled": settings.remote_enabled,
        "online": tunnel.online,
        "error": tunnel.error,
        "relay": settings.phone_relay or "",
        "this_device": this_device(request),
    }
    if out["this_device"] is None:  # the PC: its list of phones
        with _db(request)() as s:
            rows = s.scalars(select(Device).where(Device.revoked.is_(False)).order_by(Device.id))
            out["devices"] = [
                {"id": d.id, "name": d.name, "created": _iso(d.created),
                 "last_seen": _iso(d.last_seen)}
                for d in rows
            ]  # fmt: skip
    return out


class RemoteChoice(BaseModel):
    enabled: bool
    relay: str = Field("", max_length=300)  # "" = n0's public relays


@router.put("/remote")
async def set_remote(request: Request, body: RemoteChoice) -> dict[str, Any]:
    settings, tunnel = _settings(request), _tunnel(request)
    relay = clean_relay(body.relay) if body.relay else ""
    if body.relay and not relay:
        raise HTTPException(422, "A relay address starts with https://")
    was_relay = settings.phone_relay
    save_remote(settings, body.enabled, relay)
    if not body.enabled or was_relay != settings.phone_relay:
        await tunnel.stop()
        _pairing(request).code = ""
    if body.enabled:
        await tunnel.start()
    return status(request)


@router.post("/pair")
def pair(request: Request) -> dict[str, Any]:
    """A new one-time code; the QR code opens the phone app with it."""
    settings, tunnel = _settings(request), _tunnel(request)
    if not (settings.remote_enabled and tunnel.online):
        raise HTTPException(409, tunnel.error or "Turn on phone access first")
    code = _pairing(request).new(time.monotonic())
    # all in the fragment: browsers never send it, so GitHub Pages never sees it
    url = f"{PHONE_APP}#pc={tunnel.pc_id}&code={code}&relay={quote(tunnel.relay, safe='')}"
    qr = segno.make(url, error="m").png_data_uri(scale=6, border=2)
    return {"code": code, "url": url, "qr": qr, "expires_in": int(CODE_TTL)}


class Claim(BaseModel):
    code: str = Field(max_length=32)
    name: str = Field("", max_length=80)


@router.post("/claim")
def claim(request: Request, body: Claim) -> dict[str, Any]:
    """The phone trades the code for its token (through the tunnel only, so it has an iroh id)."""
    peer: str = getattr(request.state, "peer", "")  # set by LocalOnly for tunnel calls only
    if not peer:
        raise HTTPException(400, "Pair from the phone: scan the QR code")
    if not _pairing(request).claim(body.code, time.monotonic()):
        raise HTTPException(401, "That code is wrong or expired: make a new one on the PC")
    token = secrets.token_urlsafe(32)
    with _db(request)() as s:
        dev = Device(name=body.name.strip() or "Phone", token_hash=token_hash(token), peer=peer)
        s.add(dev)
        s.commit()
        dev_id = dev.id
    return {"id": dev_id, "token": token}


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
