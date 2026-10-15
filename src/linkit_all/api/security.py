"""Local-only guard: blocks DNS rebinding (Host) and cross-site requests (Origin).

The server binds to 127.0.0.1, but any web page the user visits can still try to call it
through their browser. Requests must name a loopback Host, and anything that changes state
(non-GET, or a WebSocket) must come from the app's own origin.
"""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class LocalOnly:
    def __init__(self, app: ASGIApp, extra_origins: list[str] | None = None) -> None:
        self.app = app
        self.extra_origins = set(extra_origins or [])  # e.g. the Angular dev server

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        hostname = host.rsplit(":", 1)[0] if not host.endswith("]") else host
        if hostname not in LOOPBACK:
            return await self._deny(scope, receive, send, 400, "Host not allowed")
        origin = headers.get("origin")
        unsafe = scope["type"] == "websocket" or scope["method"] not in SAFE_METHODS
        if unsafe and origin and origin != f"http://{host}" and origin not in self.extra_origins:
            return await self._deny(scope, receive, send, 403, "Cross-origin request blocked")
        await self.app(scope, receive, send)

    @staticmethod
    async def _deny(scope: Scope, receive: Receive, send: Send, status: int, text: str) -> None:
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 1008})
            return
        body = text.encode()
        headers = [(b"content-type", b"text/plain"), (b"content-length", str(len(body)).encode())]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
