"""Spike: carry the phone's HTTP calls to the local LinKit server over an iroh tunnel.

Run next to a LinKit server with phone access on (LINKIT_REMOTE_ENABLED=true,
LINKIT_REMOTE_HOSTS=["linkit.iroh"]):

    python spike/iroh-phone/bridge.py --port 8772 --key D:/linkit-test-tmp/iroh-spike/key.bin

Wire format, one bidirectional QUIC stream per request (ALPN linkit/http/1):
    request  = u32 length + JSON {"method", "path", "headers": [[k, v], ...]} + body until finish
    response = u32 length + JSON {"status", "headers": [[k, v], ...]} + body until finish
Forwarded requests carry Host linkit.iroh and x-forwarded-for, so LocalOnly treats them as
remote: the device cookie and the phone limits apply unchanged.
"""

import argparse
import asyncio
import json
import struct
import time
from collections.abc import Coroutine
from pathlib import Path

import httpx
import iroh

ALPN = b"linkit/http/1"
HOST = "linkit.iroh"
MAX_BODY = 16 * 1024 * 1024
TASKS: set[asyncio.Task[None]] = set()  # keep running tasks referenced
HOP = {"host", "content-length", "connection", "transfer-encoding", "x-forwarded-for"}


def secret_key(path: Path) -> bytes:
    """The PC's iroh identity: kept, so the address in the phone's link never changes."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(iroh.SecretKey.generate().to_bytes())
    return path.read_bytes()


def spawn(coro: Coroutine[None, None, None]) -> None:
    task = asyncio.create_task(coro)
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)


async def handle(bi: iroh.BiStream, http: httpx.AsyncClient, peer: str) -> None:
    recv, send = bi.recv(), bi.send()
    started = time.perf_counter()
    (size,) = struct.unpack(">I", await recv.read_exact(4))
    head = json.loads(await recv.read_exact(size))
    body = await recv.read_to_end(MAX_BODY)
    headers = [(k, v) for k, v in head["headers"] if k.lower() not in HOP]
    headers += [("host", HOST), ("x-forwarded-for", f"iroh:{peer}")]
    r = await http.request(head["method"], head["path"], headers=headers, content=body)
    out = json.dumps({"status": r.status_code, "headers": list(r.headers.multi_items())}).encode()
    await send.write_all(struct.pack(">I", len(out)) + out + r.content)
    await send.finish()
    ms = (time.perf_counter() - started) * 1000
    print(f"{peer} {head['method']} {head['path']} -> {r.status_code} ({ms:.0f} ms)", flush=True)


async def serve_connection(incoming: iroh.Incoming, http: httpx.AsyncClient) -> None:
    conn = await (await incoming.accept()).connect()
    peer = conn.remote_id().fmt_short()
    print("phone connected:", peer, flush=True)
    try:
        while True:
            bi = await conn.accept_bi()
            spawn(handle(bi, http, peer))
    except Exception as e:  # the phone went away
        print("phone gone:", peer, type(e).__name__, flush=True)


async def main() -> None:
    iroh.iroh_ffi.uniffi_set_event_loop(asyncio.get_running_loop())
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--key", type=Path, required=True)
    args = ap.parse_args()
    ep = await iroh.Endpoint.bind(
        iroh.EndpointOptions(preset=iroh.preset_n0(), alpns=[ALPN], secret_key=secret_key(args.key))
    )
    await ep.online()
    print("pc id:", ep.id(), flush=True)
    print("relay:", ep.addr().relay_url(), flush=True)
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}", timeout=60) as http:
        while (incoming := await ep.accept_next()) is not None:
            spawn(serve_connection(incoming, http))


if __name__ == "__main__":
    asyncio.run(main())
