"""Phone companion (docs/phone.md): remote access over the user's tailnet."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from linkit_all.api.app import create_app
from linkit_all.core.config import Settings

BASE = "http://127.0.0.1:8765"
TAILNET = "pc.tail1234.ts.net"
REMOTE = {"host": TAILNET, "x-forwarded-for": "100.64.0.7"}


def _client(tmp_path: Path, **kw: object) -> TestClient:
    return TestClient(create_app(Settings(data_dir=tmp_path / "data", **kw)), base_url=BASE)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with _client(tmp_path, remote_enabled=True, remote_hosts=[TAILNET]) as c:
        yield c


def test_remote_host_needs_remote_enabled(tmp_path: Path) -> None:
    with _client(tmp_path, remote_hosts=[TAILNET]) as c:  # listed but switched off
        assert c.get("/api/status", headers=REMOTE).status_code == 400
        assert c.get("/api/status").status_code == 200  # loopback works as before


def test_only_listed_hosts(client: TestClient) -> None:
    assert client.get("/api/status", headers={"host": "evil.example"}).status_code == 400
    assert client.get("/api/status", headers={"host": "other.tail1234.ts.net"}).status_code == 400


def test_proxied_loopback_host_counts_as_remote(tmp_path: Path) -> None:
    """Tailscale proxies from 127.0.0.1: its forwarding header marks the request remote."""
    with _client(tmp_path) as c:
        forwarded = {"x-forwarded-for": "100.64.0.7"}
        assert c.get("/api/status", headers=forwarded).status_code == 400


# --- pairing and device auth (api/devices.py) ------------------------------------------

PHONE = f"https://{TAILNET}"
FWD = {"x-forwarded-for": "100.64.0.7"}


def _pair(client: TestClient, name: str = "Pixel") -> int:
    code = client.post("/api/phone/pair").json()["code"]
    r = client.post(f"{PHONE}/api/phone/claim", json={"code": code, "name": name}, headers=FWD)
    assert r.status_code == 200, r.text
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    return int(r.json()["id"])


def test_pair_qr_and_claim(client: TestClient) -> None:
    body = client.post("/api/phone/pair").json()
    assert body["url"] == f"{PHONE}/pair#{body['code']}"
    assert body["qr"].startswith("data:image/png;base64,") and body["expires_in"] == 300
    assert client.get(f"{PHONE}/api/status", headers=FWD).status_code == 401  # not paired yet
    _pair(client)
    assert client.get(f"{PHONE}/api/status", headers=FWD).status_code == 200


def test_code_is_one_time(client: TestClient) -> None:
    code = client.post("/api/phone/pair").json()["code"]
    assert client.post("/api/phone/claim", json={"code": code}).status_code == 200
    assert client.post("/api/phone/claim", json={"code": code}).status_code == 401


def test_pairing_needs_phone_access_on(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        assert c.post("/api/phone/pair").status_code == 409


def test_middleware_matrix(client: TestClient) -> None:
    # loopback works as today, with no cookie
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/vault").status_code == 200
    # remote without a token: the app shell loads, the API does not
    assert client.get(f"{PHONE}/api/jobs", headers=FWD).status_code == 401
    assert client.get(f"{PHONE}/pair", headers=FWD).status_code in (200, 404)  # shell or unbuilt
    # remote with a token
    dev = _pair(client)
    assert client.get(f"{PHONE}/api/jobs", headers=FWD).status_code == 200
    me = client.get(f"{PHONE}/api/phone", headers=FWD).json()
    assert me["this_device"] == dev and "devices" not in me
    # PC-only routes
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
        r = client.request(method, f"{PHONE}{path}", headers={**FWD, "origin": PHONE})
        assert r.status_code == 403, (method, path, r.status_code)
    # revoked from the PC: 401 at once
    assert client.delete(f"/api/phone/devices/{dev}").status_code == 204
    assert client.get(f"{PHONE}/api/jobs", headers=FWD).status_code == 401
    assert client.get("/api/phone").json()["devices"] == []


def test_websocket_needs_a_device(client: TestClient) -> None:
    from starlette.websockets import WebSocketDisconnect

    ws_url = f"wss://{TAILNET}/api/events"
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect(ws_url, headers={**FWD, "origin": PHONE}) as ws,
    ):
        ws.receive_json()
    _pair(client)
    token = client.cookies.get("linkit_device", domain=TAILNET)
    headers = {**FWD, "origin": PHONE, "cookie": f"linkit_device={token}"}
    with client.websocket_connect(ws_url, headers=headers):
        pass  # accepted


def test_phone_cannot_change_ai_or_turn_on_auto_submit(client: TestClient) -> None:
    _pair(client)
    cfg = client.get("/api/search").json()
    put = {"headers": {**FWD, "origin": PHONE}}
    assert client.put(f"{PHONE}/api/search", json=cfg, **put).status_code == 200  # unchanged
    changed = {**cfg, "ai": {**cfg["ai"], "provider": "litellm", "api_key": "sk-x"}}
    assert client.put(f"{PHONE}/api/search", json=changed, **put).status_code == 403
    auto = {**cfg, "apply": {**cfg["apply"], "submit_without_asking": True}}
    assert client.put(f"{PHONE}/api/search", json=auto, **put).status_code == 403
    # a mail server or backup folder of the phone's choosing would leak secrets
    smtp = {**cfg, "email": {**cfg["email"], "smtp_host": "smtp.attacker.example"}}
    assert client.put(f"{PHONE}/api/search", json=smtp, **put).status_code == 403
    backup = {**cfg, "backup": {**cfg["backup"], "folder": "C:/somewhere"}}
    assert client.put(f"{PHONE}/api/search", json=backup, **put).status_code == 403
    sched = {**cfg, "schedule": {**cfg["schedule"], "enabled": not cfg["schedule"]["enabled"]}}
    assert client.put(f"{PHONE}/api/search", json=sched, **put).status_code == 200  # run options
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


def test_remote_switch_saved_in_data_folder(tmp_path: Path) -> None:
    with _client(tmp_path) as c:
        r = c.put("/api/phone/remote", json={"enabled": True, "host": f"https://{TAILNET}/"})
        assert r.status_code == 200 and r.json()["address"] == f"{PHONE}/"
        assert c.put("/api/phone/remote", json={"enabled": True, "host": "a b"}).status_code == 422
    with _client(tmp_path) as c:  # restart keeps it
        assert c.get("/api/phone").json()["enabled"] is True
        assert c.get(f"{PHONE}/api/jobs", headers=FWD).status_code == 401
