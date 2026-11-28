"""Local-only guard: blocks DNS rebinding (Host) and cross-site requests (Origin).

The server binds to 127.0.0.1, but any web page the user visits can still try to call it
through their browser. Requests must name a loopback Host, and anything that changes state
(non-GET, or a WebSocket) must come from the app's own origin.

Phone companion (docs/phone.md): a paired phone's requests arrive only through the iroh tunnel
(api/tunnel.py), which calls the app in-process with this run's secret and the phone's iroh id.
They count as remote: the device token must belong to that iroh id, and the PC-only routes stay
closed. Anything else that is not a loopback Host, or that came through a proxy, is refused.
"""

import hmac
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from linkit_all.core.config import Settings

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# set by reverse proxies: phones come through the tunnel, never through one of those
PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "forwarded", "tailscale-user-login")
TUNNEL = "x-linkit-tunnel"  # this run's secret, set only by api/tunnel.py
PEER = "x-linkit-peer"  # the phone's iroh id, set only by api/tunnel.py
# the PC only (CLAUDE.md §7 Phone): secrets, the extension's pairing code, exports, AI and other
# keys, mail passwords, and pairing itself. PUT /api/search guards the AI and auto-submit there.
REMOTE_FORBIDDEN = (
    ("", "/api/vault"),
    ("", "/api/assist/token"),
    ("", "/api/report/export"),
    ("", "/api/backup"),
    ("", "/api/keys"),
    ("", "/api/ai/check"),
    ("", "/api/phone/remote"),
    ("", "/api/phone/pair"),
    ("", "/api/phone/devices"),
    ("write", "/api/email"),
)


def remote_forbidden(method: str, path: str) -> bool:
    write = method not in SAFE_METHODS
    return any(path.startswith(prefix) and (not kind or write) for kind, prefix in REMOTE_FORBIDDEN)


def device_token(headers: dict[str, str]) -> str:
    """The phone's token from `Authorization: Bearer <token>` (sent inside the tunnel)."""
    scheme, _, token = headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


class LocalOnly:
    def __init__(
        self,
        app: ASGIApp,
        extra_origins: list[str] | None = None,
        settings: Settings | None = None,
        devices: Callable[[str, str], int | None] | None = None,
        tunnel_secret: str = "",
    ) -> None:
        self.app = app
        self.extra_origins = set(extra_origins or [])  # e.g. the Angular dev server
        self.settings = settings or Settings()  # read per request: the Phone page can change it
        self.devices = devices or (lambda token, peer: None)  # -> paired device id
        self.secret = tunnel_secret.encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        hostname = (host.rsplit(":", 1)[0] if not host.endswith("]") else host).lower()
        given = headers.get(TUNNEL, "").encode()
        remote = bool(self.secret) and bool(given) and hmac.compare_digest(given, self.secret)
        if not remote and (hostname not in LOOPBACK or any(h in headers for h in PROXY_HEADERS)):
            return await self._deny(scope, receive, send, 400, "Host not allowed")
        if remote:
            if not self.settings.remote_enabled:
                return await self._deny(scope, receive, send, 403, "Phone access is off")
            token = device_token(headers)
            # ponytail: one indexed SQLite read per phone call on the event loop; cache with
            # revoke-time invalidation if phones ever make it a bottleneck
            device = self.devices(token, headers.get(PEER, "")) if token else None
            path, method = scope["path"], scope.get("method", "GET")
            # an unpaired phone may only trade its one-time code
            if device is None and not (method == "POST" and path == "/api/phone/claim"):
                return await self._deny(scope, receive, send, 401, "Pair this phone first")
            if device is not None and remote_forbidden(method, path):
                return await self._deny(scope, receive, send, 403, "Only on the PC itself")
            state = scope.setdefault("state", {})
            state["device"], state["peer"] = device, headers.get(PEER, "")
            return await self.app(scope, receive, send)  # in-process: no browser Origin to check
        origin = headers.get("origin")
        unsafe = scope["type"] == "websocket" or scope["method"] not in SAFE_METHODS
        # the LinKit extension's own origin may call the assist API, which checks its pairing token
        extension = (
            origin
            and origin.startswith("chrome-extension://")
            and scope["path"].startswith("/api/assist/")
        )
        if (
            unsafe
            and origin
            and not extension
            and origin not in (f"http://{host}", f"https://{host}")
            and origin not in self.extra_origins
        ):
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
