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
