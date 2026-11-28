"""In-process event bus for the Live Run screen (WebSocket /api/events)."""

import asyncio
from collections import deque
from typing import TYPE_CHECKING, Any

from linkit_all.core.models import utcnow

if TYPE_CHECKING:
    from loguru import Message

Event = dict[str, Any]
REVOKED: Event = {"type": "revoked"}  # sentinel for one phone's queues only, never published


class EventBus:
    def __init__(self, history: int = 300) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._devices: dict[asyncio.Queue[Event], int] = {}  # queue -> paired phone viewing it
        self._loop: asyncio.AbstractEventLoop | None = None
        self.recent: deque[Event] = deque(maxlen=history)  # replayed to new viewers
        self.last_shot: Event | None = None  # newest live_shot: replayed, but not in `recent`

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self, device: int | None = None) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        if device is not None:
            self._devices[q] = device
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(q)
        self._devices.pop(q, None)

    def revoke(self, device: int) -> None:
        """Call on the event loop thread: ends the unpaired phone's open /events sockets."""
        for q, d in list(self._devices.items()):
            if d == device:
                if q.full():
                    q.get_nowait()
                q.put_nowait(REVOKED)

    def revoke_threadsafe(self, device: int) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self.revoke, device)

    def publish(self, event: Event) -> None:
        """Call on the event loop thread (see publish_threadsafe)."""
        event = {"at": utcnow().isoformat(timespec="seconds") + "Z", **event}
        if event.get("type") == "live_shot":  # every ~3 s: keep only the newest, not the log
            self.last_shot = event
        else:
            self.recent.append(event)
        for q in list(self._subscribers):
            if not q.full():  # a stalled browser tab drops events instead of blocking runs
                q.put_nowait(event)

    def publish_threadsafe(self, event: Event) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self.publish, event)

    def log_sink(self, message: "Message") -> None:
        """loguru sink: app log lines (already secret-redacted) become live events."""
        record = message.record
        event: Event = {
            "type": "log", "level": record["level"].name, "message": record["message"],
        }  # fmt: skip
        extra = record["extra"]  # logger.bind(code=..., params=...): the UI translates it
        if "code" in extra:
            event |= {"code": extra["code"], "params": extra.get("params") or {}}
        self.publish_threadsafe(event)
