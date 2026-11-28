"""Phone companion (docs/phone.md): phones reach the PC only through the iroh tunnel."""

import json
import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
import pytest
from fastapi.testclient import TestClient

from linkit_all.api.app import create_app
from linkit_all.api.devices import PHONE_APP
from linkit_all.api.security import PEER, TUNNEL
from linkit_all.api.tunnel import Tunnel
from linkit_all.core.config import Settings

BASE = "http://127.0.0.1:8765"
PC_ID = "f" * 64
RELAY = "https://euc1-1.relay.n0.iroh.link./"
PHONE_ID = "a" * 64


class _Endpoint:
    async def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def offline_tunnel(monkeypatch: pytest.MonkeyPatch) -> None:
    """No network in tests: the tunnel "connects" at once with a fixed id and relay."""

    async def start(self: Tunnel) -> None:
        self._endpoint, self.pc_id, self.relay = _Endpoint(), PC_ID, RELAY  # type: ignore[assignment]

    monkeypatch.setattr(Tunnel, "start", start)


def _client(tmp_path: Path, **kw: object) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path / "data", **kw)), base_url=BASE)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with _client(tmp_path, remote_enabled=True) as c:
        yield c


class Phone:
    """What api/tunnel.py does for a phone: in-process calls with this run's secret."""

    def __init__(self, client: TestClient, peer: str = PHONE_ID) -> None:
        self.client, self.peer, self.token = client, peer, ""

    def headers(self) -> dict[str, str]:
        secret = self.client.app.state.tunnel.secret  # type: ignore[attr-defined]
        h = {"host": "linkit.tunnel", TUNNEL: secret, PEER: self.peer}
        return h | ({"authorization": f"Bearer {self.token}"} if self.token else {})

    def request(self, method: str, path: str, **kw: Any) -> httpx.Response:
        return self.client.request(
            method, f"http://linkit.tunnel{path}", headers=self.headers(), **kw
        )

    def get(self, path: str) -> httpx.Response:
        return self.request("GET", path)

    def put(self, path: str, body: Any) -> httpx.Response:
        return self.request("PUT", path, json=body)

    def pair(self, name: str = "Pixel") -> int:
        code = self.client.post("/api/phone/pair").json()["code"]
        r = self.request("POST", "/api/phone/claim", json={"code": code, "name": name})
        assert r.status_code == 200, r.text
        self.token = r.json()["token"]
        return int(r.json()["id"])


# --- the guard (api/security.py) -----------------------------------------------------------


def test_only_loopback_or_the_tunnel(client: TestClient) -> None:
    assert client.get("/api/status").status_code == 200  # the PC itself, as before
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/status", headers={"x-forwarded-for": "100.64.0.7"}).status_code == 400
    forged = {"host": "linkit.tunnel", TUNNEL: "guess", PEER: PHONE_ID}
    assert client.get("/api/status", headers=forged).status_code == 400  # wrong secret
    assert Phone(client).get("/api/status").status_code == 401  # right secret, not paired


def test_tunnel_needs_phone_access_on(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert Phone(c).get("/api/status").status_code == 403
        assert c.post("/api/phone/pair").status_code == 409


def test_pair_link_holds_pc_id_code_and_relay(client: TestClient) -> None:
    body = client.post("/api/phone/pair").json()
    assert body["url"] == (
        f"{PHONE_APP}#pc={PC_ID}&code={body['code']}&relay={quote(RELAY, safe='')}"
    )
    assert PHONE_APP == "https://linkit-all.github.io/app/"
    assert body["qr"].startswith("data:image/png;base64,") and body["expires_in"] == 300
    phone = Phone(client)
    assert phone.get("/api/status").status_code == 401
    phone.pair()
    assert phone.get("/api/status").status_code == 200


def test_pairing_waits_for_the_tunnel(client: TestClient) -> None:
    tunnel = client.app.state.tunnel  # type: ignore[attr-defined]
    tunnel._endpoint, tunnel.error = None, "Could not reach the phone relay (TimeoutError)"
    r = client.post("/api/phone/pair")
    assert r.status_code == 409 and "relay" in r.json()["detail"]


def test_claim_only_through_the_tunnel(client: TestClient) -> None:
    code = client.post("/api/phone/pair").json()["code"]
    assert client.post("/api/phone/claim", json={"code": code}).status_code == 400  # from the PC
    forged = {PEER: PHONE_ID}  # a raw header from the PC is not a phone
    assert client.post("/api/phone/claim", json={"code": code}, headers=forged).status_code == 400
    phone = Phone(client)
    assert phone.request("POST", "/api/phone/claim", json={"code": code}).status_code == 200
    assert phone.request("POST", "/api/phone/claim", json={"code": code}).status_code == 401


def test_token_works_only_from_its_phone(client: TestClient) -> None:
    phone = Phone(client)
    phone.pair()
    thief = Phone(client, peer="b" * 64)
    thief.token = phone.token
    assert thief.get("/api/jobs").status_code == 401
    assert phone.get("/api/jobs").status_code == 200


def test_middleware_matrix(client: TestClient) -> None:
    assert client.get("/api/vault").status_code == 200  # the PC, no token
    phone = Phone(client)
    assert phone.get("/api/jobs").status_code == 401
    dev = phone.pair()
    assert phone.get("/api/jobs").status_code == 200
    me = phone.get("/api/phone").json()
    assert me["this_device"] == dev and "devices" not in me
    for method, path in [
        ("GET", "/api/vault"),
        ("POST", "/api/vault/export"),
        ("GET", "/api/assist/token"),
        ("GET", "/api/report/export.csv"),
        ("GET", "/api/report/export.pdf"),
        ("GET", "/api/backup"),
        ("PUT", "/api/keys/adzuna"),
        ("POST", "/api/ai/check"),
        ("POST", "/api/email"),
        ("POST", "/api/phone/pair"),
        ("PUT", "/api/phone/remote"),
        ("DELETE", f"/api/phone/devices/{dev}"),
    ]:
        r = phone.request(method, path)
        assert r.status_code == 403, (method, path, r.status_code)
    assert client.delete(f"/api/phone/devices/{dev}").status_code == 204
    assert phone.get("/api/jobs").status_code == 401  # unpaired: at once
    assert client.get("/api/phone").json()["devices"] == []


def test_phone_cannot_change_ai_or_turn_on_auto_submit(client: TestClient) -> None:
    phone = Phone(client)
    phone.pair()
    cfg = client.get("/api/search").json()
    assert phone.put("/api/search", cfg).status_code == 200  # unchanged
    changed = {**cfg, "ai": {**cfg["ai"], "provider": "litellm", "api_key": "sk-x"}}
    assert phone.put("/api/search", changed).status_code == 403
    auto = {**cfg, "apply": {**cfg["apply"], "submit_without_asking": True}}
    assert phone.put("/api/search", auto).status_code == 403
    # a mail server or backup folder of the phone's choosing would leak secrets
    smtp = {**cfg, "email": {**cfg["email"], "smtp_host": "smtp.attacker.example"}}
    assert phone.put("/api/search", smtp).status_code == 403
    backup = {**cfg, "backup": {**cfg["backup"], "folder": "C:/somewhere"}}
    assert phone.put("/api/search", backup).status_code == 403
    sched = {**cfg, "schedule": {**cfg["schedule"], "enabled": not cfg["schedule"]["enabled"]}}
    assert phone.put("/api/search", sched).status_code == 200  # run options
    assert client.put("/api/search", json=auto).status_code == 200  # the PC may


def test_pairing_code_expires_and_rate_limits() -> None:
    from fastapi import HTTPException

    from linkit_all.api.devices import CODE_TTL, Pairing

    p = Pairing()
    code = p.new(now=1000.0)
    assert not p.claim(code, now=1000.0 + CODE_TTL + 1)  # expired
    code = p.new(now=2000.0)
    assert p.claim(code.lower(), now=2001.0)  # case-insensitive, then spent
    code = p.new(now=3000.0)
    for _ in range(5):
        assert not p.claim("WRONG", now=3001.0)
    with pytest.raises(HTTPException) as err:
        p.claim(code, now=3002.0)  # locked for a minute, and the code is gone
    assert err.value.status_code == 429
    assert not p.claim(code, now=3100.0)


def test_phone_access_and_relay_saved_in_data_folder(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert (
            c.put("/api/phone/remote", json={"enabled": True, "relay": "ftp://x"}).status_code
            == 422
        )
        r = c.put("/api/phone/remote", json={"enabled": True, "relay": "https://relay.example/"})
        assert r.status_code == 200 and r.json()["online"] and r.json()["relay"]
    with _client(tmp_path) as c:  # restart keeps it, and the tunnel comes back on
        status = c.get("/api/phone").json()
        assert status["enabled"] is True and status["relay"] == "https://relay.example/"
        assert c.app.state.settings.phone_relay == "https://relay.example/"  # type: ignore[attr-defined]
        assert Phone(c).get("/api/jobs").status_code == 401
        r = c.put("/api/phone/remote", json={"enabled": False})
        assert r.status_code == 200 and not r.json()["online"]


# --- the tunnel itself (api/tunnel.py) -----------------------------------------------------


def _messages(chunks: list[bytes]) -> list[dict[str, Any]]:
    data, out = b"".join(chunks), []
    while data:
        (n,) = struct.unpack(">I", data[:4])
        out.append(json.loads(data[4 : 4 + n]))
        data = data[4 + n :]
    return out


def test_tunnel_request_frames(client: TestClient) -> None:
    phone = Phone(client)
    phone.pair()
    tunnel = client.app.state.tunnel  # type: ignore[attr-defined]
    head = {"method": "GET", "path": "/api/phone",
            "headers": [["authorization", f"Bearer {phone.token}"], [TUNNEL, "spoof"]]}  # fmt: skip

    async def go() -> bytes:
        transport = httpx.ASGITransport(app=client.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://linkit.tunnel") as http:
            out: bytes = await tunnel.request(http, head, b"", PHONE_ID)
            return out

    raw = client.portal.call(go)  # type: ignore[union-attr]
    (n,) = struct.unpack(">I", raw[:4])
    reply = json.loads(raw[4 : 4 + n])
    assert reply["status"] == 200 and json.loads(raw[4 + n :])["this_device"] is not None


def test_live_events_need_pairing_and_end_on_unpair(client: TestClient) -> None:
    import anyio

    tunnel = client.app.state.tunnel  # type: ignore[attr-defined]
    phone = Phone(client)
    chunks: list[bytes] = []

    async def write(b: bytes) -> None:
        chunks.append(b)

    def head() -> dict[str, Any]:
        return {"method": "GET", "path": "/api/events", "stream": True,
                "headers": [["authorization", f"Bearer {phone.token}"]]}  # fmt: skip

    client.portal.call(tunnel.events, head(), PHONE_ID, write)  # type: ignore[union-attr]
    assert _messages(chunks)[0]["status"] == 401
    dev = phone.pair()
    chunks.clear()

    async def watch_then_unpair() -> None:
        with anyio.fail_after(5):  # the stream must end by itself once unpaired
            async with anyio.create_task_group() as tg:
                tg.start_soon(tunnel.events, head(), PHONE_ID, write)
                await anyio.sleep(0.1)
                tunnel.bus.publish({"type": "stage", "stage": "apply", "status": "started"})
                await anyio.sleep(0.1)
                tunnel.bus.revoke(dev)  # what DELETE /api/phone/devices/{id} triggers

    client.portal.call(watch_then_unpair)  # type: ignore[union-attr]
    msgs = _messages(chunks)
    assert msgs[0]["status"] == 200
    assert any(m.get("type") == "stage" for m in msgs[1:])  # then it ended on its own


# --- web push (api/push.py) ----------------------------------------------------------------

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123"
SUB = {"endpoint": ENDPOINT, "keys": {"p256dh": "BPk3", "auth": "c2Vj"}}


def _park(client: TestClient) -> None:
    from linkit_all.core.models import ActionItem, ActionKind, Job, JobState

    with client.app.state.db.begin() as s:  # type: ignore[attr-defined]
        n = s.query(Job).count()
        job = Job(source="lever", url=f"https://x/{n}", title="Secret Title", company="Acme Corp",
                  dedupe_hash=f"h{n}", state=JobState.needs_user)  # fmt: skip
        s.add(job)
        s.flush()
        s.add(ActionItem(job_id=job.id, kind=ActionKind.apply_by_hand))


@pytest.fixture
def pushes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    from linkit_all.api import push

    sent: list[dict[str, object]] = []
    monkeypatch.setattr(push, "webpush", lambda info, **kw: sent.append({"info": info, **kw}))
    return sent


def test_push_payload_is_only_the_count(
    client: TestClient, pushes: list[dict[str, object]]
) -> None:
    from linkit_all.api.push import send

    phone = Phone(client)
    phone.pair()
    key = phone.get("/api/phone/push").json()["public_key"]
    assert len(key) == 87  # uncompressed P-256 point, base64url without padding
    assert phone.put("/api/phone/push", SUB).status_code == 204
    _park(client)
    _park(client)
    app = client.app
    assert send(app.state.db, app.state.settings, 2) == 1  # type: ignore[attr-defined]
    data = str(pushes[0]["data"])
    assert json.loads(data) == {"count": 2}
    assert "Secret" not in data and "Acme" not in data
    assert pushes[0]["vapid_claims"] == {"sub": "https://github.com/silentco2/LinKit-All"}


def test_push_sent_when_more_wait_after_a_stage(
    client: TestClient, pushes: list[dict[str, object]]
) -> None:
    import time

    phone = Phone(client)
    phone.pair()
    phone.get("/api/phone/push")
    phone.put("/api/phone/push", SUB)
    _park(client)
    bus = client.app.state.bus  # type: ignore[attr-defined]
    bus.publish_threadsafe({"type": "stage", "stage": "apply", "status": "started"})
    bus.publish_threadsafe({"type": "stage", "stage": "apply", "status": "finished"})
    for _ in range(50):
        if pushes:
            break
        time.sleep(0.05)
    assert [p["data"] for p in pushes] == ['{"count": 1}']


def test_push_routes_are_for_phones_and_push_services(client: TestClient) -> None:
    assert client.get("/api/phone/push").status_code == 403  # the PC has desktop notifications
    phone = Phone(client)
    phone.pair()
    for endpoint in (
        "https://192.168.1.1/admin",
        "http://fcm.googleapis.com/x",
        "https://fcm.googleapis.com.evil.example/x",
    ):
        assert phone.put("/api/phone/push", {**SUB, "endpoint": endpoint}).status_code == 422


def test_revoke_drops_push(client: TestClient, pushes: list[dict[str, object]]) -> None:
    from linkit_all.api.push import send

    phone = Phone(client)
    dev = phone.pair()
    phone.get("/api/phone/push")
    phone.put("/api/phone/push", SUB)
    client.delete(f"/api/phone/devices/{dev}")
    app = client.app
    assert send(app.state.db, app.state.settings, 3) == 0  # type: ignore[attr-defined]


# --- the PC's own UI ------------------------------------------------------------------------


def test_spa_never_touches_a_network_share(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`//host/share` would make Windows open an SMB link and send the user's NTLM hash."""
    touched: list[str] = []
    resolve = Path.resolve

    def spy(self: Path, strict: bool = False) -> Path:
        touched.append(str(self))
        return resolve(self, strict)

    monkeypatch.setattr(Path, "resolve", spy)
    for url in ("/%2F%2Fevil/share/x.js", "/%5C%5Cevil%5Cshare%5Cx.js", "/C:/evil/x.js"):
        assert client.get(url).status_code in (200, 404)  # the app shell, or "UI not built"
    assert not [p for p in touched if "evil" in p]


def test_real_iroh_round_trip_on_loopback(client: TestClient) -> None:
    """The real accept/stream path with the iroh library: endpoints on this machine only,
    no relay and no internet (preset_minimal + relays off)."""
    import asyncio

    import iroh

    from linkit_all.api.tunnel import ALPN, frame

    tunnel = client.app.state.tunnel  # type: ignore[attr-defined]
    code = client.post("/api/phone/pair").json()["code"]
    local = {"preset": iroh.preset_minimal(), "relay_mode": iroh.RelayMode.disabled()}

    async def call(conn: Any, method: str, path: str, token: str = "", body: Any = None) -> Any:
        bi = await conn.open_bi()
        headers = [["authorization", f"Bearer {token}"]] if token else []
        data = json.dumps(body).encode() if body is not None else b""
        if body is not None:
            headers.append(["content-type", "application/json"])
        await bi.send().write_all(frame({"method": method, "path": path, "headers": headers}, data))
        await bi.send().finish()
        raw = await asyncio.wait_for(bi.recv().read_to_end(1 << 20), 10)
        (n,) = struct.unpack(">I", raw[:4])
        return json.loads(raw[4 : 4 + n])["status"], raw[4 + n :]

    async def go() -> list[int]:
        iroh.iroh_ffi.uniffi_set_event_loop(asyncio.get_running_loop())  # type: ignore[arg-type]
        pc = await iroh.Endpoint.bind(iroh.EndpointOptions(alpns=[ALPN], **local))
        mobile = await iroh.Endpoint.bind(iroh.EndpointOptions(**local))
        other = await iroh.Endpoint.bind(iroh.EndpointOptions(**local))
        accept = asyncio.create_task(tunnel._accept(pc))
        try:
            conn = await asyncio.wait_for(mobile.connect(pc.addr(), ALPN), 10)
            status, body = await call(conn, "POST", "/api/phone/claim", body={"code": code})
            token = json.loads(body)["token"]
            ok, _ = await call(conn, "GET", "/api/jobs", token)
            stolen = await asyncio.wait_for(other.connect(pc.addr(), ALPN), 10)
            refused, _ = await call(stolen, "GET", "/api/jobs", token)
            return [status, ok, refused]
        finally:
            accept.cancel()
            for ep in (mobile, other, pc):
                await ep.close()

    # paired over the real tunnel; the token works from that phone only
    assert client.portal.call(go) == [200, 200, 401]  # type: ignore[union-attr]


# --- linkit rc: remote control from a terminal ------------------------------------------


def test_rc_turns_remote_control_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`linkit rc` saves the switch, starts the server with no browser tab and pairs in the terminal."""
    from typer.testing import CliRunner

    from linkit_all import cli
    from linkit_all.core.config import get_settings

    monkeypatch.setenv("LINKIT_DATA_DIR", str(tmp_path / "data"))
    started: list[dict[str, Any]] = []
    monkeypatch.setattr("linkit_all.api.app.serve", lambda **kw: started.append(kw))
    monkeypatch.setattr(cli, "_pair_in_terminal", lambda port: None)
    get_settings.cache_clear()
    try:
        out = CliRunner().invoke(cli.app, ["rc", "--port", "8799"])
    finally:
        get_settings.cache_clear()
    assert out.exit_code == 0, out.output
    assert started == [{"port": 8799, "open_browser": False}]
    saved = json.loads((tmp_path / "data" / "phone.json").read_text("utf-8"))
    assert saved == {"enabled": True, "relay": ""}


def test_rc_prints_a_new_qr_code_on_enter(
    client: TestClient, capsys: pytest.CaptureFixture[str]
) -> None:
    from linkit_all.cli import _pairing_loop

    answers = iter([""])  # Enter once, then the keyboard is gone

    def ask() -> str:
        try:
            return next(answers)
        except StopIteration:
            raise EOFError from None

    _pairing_loop(client, ask=ask, wait=0)
    out = capsys.readouterr().out
    links = [line for line in out.splitlines() if line.startswith(PHONE_APP)]
    assert len(links) == 2 and links[0] != links[1]  # a fresh one-time code each time
    assert f"#pc={PC_ID}&code=" in links[0]
    assert "\u2588" in out  # the QR code itself, in block characters
    # the code printed in the terminal pairs a phone
    code = links[1].split("code=")[1].split("&")[0]
    phone = Phone(client)
    r = phone.request("POST", "/api/phone/claim", json={"code": code, "name": "Pixel"})
    assert r.status_code == 200, r.text


def test_rc_says_why_without_a_tunnel(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from linkit_all.cli import _pairing_loop

    with _client(tmp_path) as c:  # remote control off: the tunnel never comes online
        _pairing_loop(c, ask=lambda: "", wait=0, tries=2)
    err = capsys.readouterr().err
    assert "Remote control is not available" in err
