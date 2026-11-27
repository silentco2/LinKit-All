"""The PC's end of the phone tunnel (CLAUDE.md §2, docs/phone.md).

The phone web app (linkit-all.github.io/app/) dials this PC by its iroh id. iroh carries the
connection end-to-end encrypted, directly or through a relay (n0's public ones unless
`phone_relay` is set); the PC only connects out and opens no port.

Wire format, ALPN `linkit/http/1`, one bidirectional stream per request:
    request  = u32 length + JSON {"method", "path", "headers": [[k, v], ...], "stream"?} + body
    response = u32 length + JSON {"status", "headers": [[k, v], ...]} + body
A request with "stream": true for /api/events gets the live events instead: after the head,
one u32-length-prefixed JSON message per event until the phone closes the stream.

Requests go into the app in-process with two headers only this process can set: the per-run
secret (security.TUNNEL) and the phone's iroh id (security.PEER), so LocalOnly treats them as
remote and checks the device token against the key the phone paired with.
"""

import asyncio
import json
import secrets
import struct
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
from loguru import logger

from linkit_all.api.events import REVOKED, EventBus
from linkit_all.api.security import PEER, TUNNEL, device_token
from linkit_all.core.config import Settings

if TYPE_CHECKING:
    import iroh

ALPN = b"linkit/http/1"
MAX_HEAD = 64 * 1024
MAX_BODY = 16 * 1024 * 1024
HOP = {"host", "content-length", "connection", "transfer-encoding", TUNNEL, PEER}

Devices = Callable[[str, str], int | None]  # (token, phone iroh id) -> paired device id


def frame(head: dict[str, Any], body: bytes = b"") -> bytes:
    raw = json.dumps(head).encode()
    return struct.pack(">I", len(raw)) + raw + body


class Tunnel:
    """Started and stopped with phone access (Settings > Phone); one per app."""

    def __init__(self, app: Any, settings: Settings, bus: EventBus, devices: Devices) -> None:
        self.app, self.settings, self.bus, self.devices = app, settings, bus, devices
        self.secret = secrets.token_urlsafe(24)  # in memory only: a new one each run
        self.pc_id = ""
        self.relay = ""
        self.error = ""
        self._endpoint: iroh.Endpoint | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def online(self) -> bool:
        return self._endpoint is not None

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _key(self) -> bytes:
        """The PC's iroh identity, kept so pairing links stay valid across restarts."""
        import iroh

        path: Path = self.settings.data_dir / "phone_key.bin"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(iroh.SecretKey.generate().to_bytes())
        return path.read_bytes()

    async def start(self) -> None:
        if self.online:
            return
        try:
            import iroh
        except ImportError:
            self.error = "Phone access is not available on this computer (no iroh build for it)"
            return
        loop = asyncio.get_running_loop()
        iroh.iroh_ffi.uniffi_set_event_loop(loop)  # type: ignore[arg-type]  # any running loop
        options: dict[str, Any] = {
            "preset": iroh.preset_n0(), "alpns": [ALPN], "secret_key": self._key()
        }  # fmt: skip
        if self.settings.phone_relay:  # the user's own relay instead of n0's public ones
            options["relay_mode"] = iroh.RelayMode.custom_from_urls([self.settings.phone_relay])
        try:
            endpoint = await iroh.Endpoint.bind(iroh.EndpointOptions(**options))
            await asyncio.wait_for(endpoint.online(), timeout=30)
        except Exception as e:  # no network, relay down: the Phone page says so
            self.error = f"Could not reach the phone relay ({type(e).__name__})"
            logger.warning("phone tunnel offline: {}", type(e).__name__)
            return
        self._endpoint, self.error = endpoint, ""
        self.pc_id = str(endpoint.id())
        self.relay = str(endpoint.addr().relay_url() or "")
        self._spawn(self._accept(endpoint))
        logger.info("phone tunnel online")

    async def stop(self) -> None:
        endpoint, self._endpoint = self._endpoint, None
        for task in list(self._tasks):
            task.cancel()
        if endpoint is not None:
            await endpoint.close()

    async def _accept(self, endpoint: "iroh.Endpoint") -> None:
        while (incoming := await endpoint.accept_next()) is not None:
            self._spawn(self._connection(incoming))

    async def _connection(self, incoming: "iroh.Incoming") -> None:
        try:
            conn = await (await incoming.accept()).connect()
        except Exception:  # a dial that gave up half way
            return
        peer = str(conn.remote_id())
        transport = httpx.ASGITransport(app=self.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://linkit.tunnel") as http:
            try:
                while True:
                    bi = await conn.accept_bi()
                    self._spawn(self._stream(bi, http, peer))
            except Exception:  # the phone went away
                return

    async def _stream(self, bi: "iroh.BiStream", http: httpx.AsyncClient, peer: str) -> None:
        recv, send = bi.recv(), bi.send()
        try:
            (size,) = struct.unpack(">I", await recv.read_exact(4))
            if size > MAX_HEAD:
                raise ValueError("head too large")
            head = json.loads(await recv.read_exact(size))
            body = await recv.read_to_end(MAX_BODY)
            if head.get("stream") and head.get("path") == "/api/events":
                await self.events(head, peer, send.write_all)
            else:
                await send.write_all(await self.request(http, head, body, peer))
            await send.finish()
        except Exception as e:  # a broken or hostile frame ends only this stream
            logger.debug("phone tunnel stream ended: {}", type(e).__name__)

    async def request(
        self, http: httpx.AsyncClient, head: dict[str, Any], body: bytes, peer: str
    ) -> bytes:
        """One phone request through the app, as a response frame."""
        headers = [
            (str(k), str(v)) for k, v in head.get("headers", []) if str(k).lower() not in HOP
        ]
        headers += [(TUNNEL, self.secret), (PEER, peer)]
        r = await http.request(
            str(head.get("method", "GET")),
            str(head.get("path", "/")),
            headers=headers,
            content=body,
        )
        return frame({"status": r.status_code, "headers": list(r.headers.multi_items())}, r.content)

    async def events(
        self,
        head: dict[str, Any],
        peer: str,
        write: Callable[[bytes], Coroutine[Any, Any, None]],
    ) -> None:
        """The live view for a paired phone: replayed history, then each new event."""
        token = device_token({str(k).lower(): str(v) for k, v in head.get("headers", [])})
        device = self.devices(token, peer) if token else None
        if device is None:
            await write(frame({"status": 401, "headers": []}))  # every message is JSON
            return
        await write(frame({"status": 200, "headers": []}))
        q = self.bus.subscribe(device)
        try:
            for event in [*self.bus.recent, *([self.bus.last_shot] if self.bus.last_shot else [])]:
                await write(frame(event))
            while (event := await q.get()) is not REVOKED:
                await write(frame(event))
        finally:
            self.bus.unsubscribe(q)
