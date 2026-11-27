"""Local-only guard: blocks DNS rebinding (Host) and cross-site requests (Origin).

The server binds to 127.0.0.1, but any web page the user visits can still try to call it
through their browser. Requests must name a loopback Host, and anything that changes state
(non-GET, or a WebSocket) must come from the app's own origin.

Phone companion (docs/phone.md): when `remote_enabled` is on, the PC's tailnet name from
`tailscale serve` is a Host too. Tailscale proxies from 127.0.0.1, so a request counts as
remote by its Host or by the proxy's forwarding headers, never by its client address.
"""

from collections.abc import Awaitable, Callable, MutableMapping
from http.cookies import CookieError, SimpleCookie
from typing import Any

from linkit_all.core.config import Settings

Scope = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[MutableMapping[str, Any]]]
Send = Callable[[MutableMapping[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# set by `tailscale serve` (and any other reverse proxy): a local browser never sends them
PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "forwarded", "tailscale-user-login")
DEVICE_COOKIE = "linkit_device"  # api/devices.py
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


def _cookie(headers: dict[str, str], name: str) -> str:
    try:
        morsel = SimpleCookie(headers.get("cookie", "")).get(name)
    except CookieError:
        return ""
    return morsel.value if morsel else ""


class LocalOnly:
    def __init__(
        self,
        app: ASGIApp,
        extra_origins: list[str] | None = None,
        settings: Settings | None = None,
        devices: Callable[[str], int | None] | None = None,
    ) -> None:
        self.app = app
        self.extra_origins = set(extra_origins or [])  # e.g. the Angular dev server
        self.settings = settings or Settings()  # read per request: the Phone page can change it
        self.devices = devices or (lambda token: None)  # token -> paired device id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        hostname = (host.rsplit(":", 1)[0] if not host.endswith("]") else host).lower()
        remote = hostname not in LOOPBACK or any(h in headers for h in PROXY_HEADERS)
        if remote and not (
            self.settings.remote_enabled
            and hostname in {h.lower() for h in self.settings.remote_hosts}
        ):
            return await self._deny(scope, receive, send, 400, "Host not allowed")
        if remote:
            token = _cookie(headers, DEVICE_COOKIE)
            # ponytail: one indexed SQLite read per remote call on the event loop; cache with
            # revoke-time invalidation if phones ever make it a bottleneck
            device = self.devices(token) if token else None
            path, method = scope["path"], scope.get("method", "GET")
            api = path.startswith("/api/") or scope["type"] == "websocket"
            # unpaired phones get the app shell (no personal data) and the pairing call only
            if device is None and api and not (method == "POST" and path == "/api/phone/claim"):
                return await self._deny(scope, receive, send, 401, "Pair this phone first")
            if device is not None and remote_forbidden(method, path):
                return await self._deny(scope, receive, send, 403, "Only on the PC itself")
            scope.setdefault("state", {})["device"] = device
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
