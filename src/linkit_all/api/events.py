"""In-process event bus for the Live Run screen (WebSocket /api/events)."""

import asyncio
from collections import deque
from typing import TYPE_CHECKING, Any

from linkit_all.core.models import utcnow

if TYPE_CHECKING:
    from loguru import Message

Event = dict[str, Any]


class EventBus:
    def __init__(self, history: int = 300) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self.recent: deque[Event] = deque(maxlen=history)  # replayed to new viewers

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(q)

    def publish(self, event: Event) -> None:
        """Call on the event loop thread (see publish_threadsafe)."""
        event = {"at": utcnow().isoformat(timespec="seconds") + "Z", **event}
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
        self.publish_threadsafe(
            {"type": "log", "level": record["level"].name, "message": record["message"]}
        )
