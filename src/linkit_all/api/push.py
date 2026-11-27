"""Web push to paired phones (CLAUDE.md §2, docs/phone.md).

Sent on the same news as the desktop notification: after a stage or run ends, when more things
wait for the user than before. The payload is exactly `{"count": n}`, shown on the phone as
"LinKit needs you (n)": no job, company or personal text leaves the PC this way. VAPID keys are
made on first use and kept in the data folder.
"""

import asyncio
import base64
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from py_vapid import Vapid01
from pydantic import BaseModel, Field
from pywebpush import WebPushException, webpush
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.api.events import EventBus
from linkit_all.core.config import Settings
from linkit_all.core.models import ActionItem, ActionStatus, Device, PushSubscription
from linkit_all.core.search import load_search

# Only the browsers' own push services: the PC never posts to an address a phone made up.
PUSH_HOSTS = (
    "fcm.googleapis.com",  # Chrome, Edge, Samsung Internet on Android
    "push.services.mozilla.com",  # Firefox
    "push.apple.com",  # Safari on iPhone (home-screen app)
    "notify.windows.com",  # Edge on Windows
)
CONTACT = "https://github.com/silentco2/LinKit-All"  # VAPID `sub`: the project, never the user

router = APIRouter(prefix="/api/phone/push")


def payload(count: int) -> str:
    return json.dumps({"count": count})


def push_host_ok(url: str) -> bool:
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def _key_file(settings: Settings) -> Path:
    return settings.data_dir / "vapid_private.pem"


def public_key(settings: Settings) -> str:
    """The VAPID public key for PushManager.subscribe, making the key pair on first use."""
    path = _key_file(settings)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        fresh = Vapid01()
        fresh.generate_keys()
        fresh.save_key(str(path))
    raw = Vapid01.from_file(str(path)).public_key.public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint
    )
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def needs_count(db: sessionmaker[Session], settings: Settings) -> int:
    """What the Needs you badge counts as parked: open action items, plus a Google check."""
    from sqlalchemy import func

    from linkit_all.sources.linkedin_posts.source import check_flag

    with db() as s:
        n = s.scalar(select(func.count()).where(ActionItem.status == ActionStatus.open)) or 0
    cfg = load_search(db)
    if cfg and "linkedin_posts" in cfg.sources.enabled and check_flag(settings.data_dir).exists():
        n += 1
    return n


def send(db: sessionmaker[Session], settings: Settings, count: int) -> int:
    """Push the count to every paired phone that asked for it; returns how many were sent."""
    key = _key_file(settings)
    if not key.exists():
        return 0
    with db() as s:
        subs = s.scalars(
            select(PushSubscription).join(Device).where(Device.revoked.is_(False))
        ).all()
    sent, gone = 0, []
    for sub in subs:
        info = {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
        try:
            webpush(info, data=payload(count), vapid_private_key=str(key),
                    vapid_claims={"sub": CONTACT}, timeout=10, ttl=3600)  # fmt: skip
            sent += 1
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            if status in (404, 410):  # the phone dropped the subscription
                gone.append(sub.id)
            else:
                logger.warning("push to a paired phone failed ({})", status)
        except Exception as e:  # network trouble: the in-app badge still shows it
            logger.warning("push to a paired phone failed: {}", type(e).__name__)
    if gone:
        with db.begin() as s:
            s.execute(delete(PushSubscription).where(PushSubscription.id.in_(gone)))
    return sent


async def watch(bus: EventBus, db: sessionmaker[Session], settings: Settings) -> None:
    """Background task: after each stage or run ends, push when the parked count went up."""
    last = await asyncio.to_thread(needs_count, db, settings)
    q = bus.subscribe()
    try:
        while True:
            event = await q.get()
            if event.get("type") not in ("run", "stage") or event.get("status") == "started":
                continue
            n = await asyncio.to_thread(needs_count, db, settings)
            if n > last:
                await asyncio.to_thread(send, db, settings, n)
            last = n
    finally:
        bus.unsubscribe(q)


# --- routes: the phone's "Notify me on this phone" switch ------------------------------


def _device(request: Request) -> int:
    device: int | None = getattr(request.state, "device", None)
    if device is None:
        raise HTTPException(403, "Push is for paired phones")
    return device


def _db(request: Request) -> sessionmaker[Session]:
    db: sessionmaker[Session] = request.app.state.db
    return db


@router.get("")
def get_key(request: Request) -> dict[str, Any]:
    device = _device(request)
    with _db(request)() as s:
        on = s.scalar(select(PushSubscription.id).where(PushSubscription.device_id == device))
    return {"public_key": public_key(request.app.state.settings), "subscribed": on is not None}


class Keys(BaseModel):
    p256dh: str = Field(max_length=255)
    auth: str = Field(max_length=255)


class Subscription(BaseModel):
    endpoint: str = Field(max_length=1024)
    keys: Keys


@router.put("", status_code=204)
def subscribe(request: Request, body: Subscription) -> None:
    device = _device(request)
    if not push_host_ok(body.endpoint):
        raise HTTPException(422, "Not a browser push service")
    with _db(request).begin() as s:
        s.execute(delete(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
        s.add(PushSubscription(device_id=device, endpoint=body.endpoint,
                               p256dh=body.keys.p256dh, auth=body.keys.auth))  # fmt: skip


@router.delete("", status_code=204)
def unsubscribe(request: Request) -> None:
    device = _device(request)
    with _db(request).begin() as s:
        s.execute(delete(PushSubscription).where(PushSubscription.device_id == device))
