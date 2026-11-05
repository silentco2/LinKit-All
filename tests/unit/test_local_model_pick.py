# ruff: noqa: F811
"""Picking a local model (Ollama / LM Studio) in the welcome flow, against fake local servers.

The fakes are real HTTP servers on free 127.0.0.1 ports, so `/api/ai/local` and `/api/ai/check`
(the real LiteLLM client) run unmodified; only the two probe URLs are re-pointed. The opt-in live
test scans the real servers: set LINKIT_LIVE_OLLAMA=1 and/or LINKIT_LIVE_LMSTUDIO=1, run
`pytest -m live`.
"""

import json
import os
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_api import SAME_ORIGIN, client, mem_keyring  # noqa: F401  (fixtures)

from linkit_all.api import routes

# LiteLLM downloads its price list on import unless told to use the bundled copy.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

Seen = list[dict[str, Any]]


class FakeLocalAI(BaseHTTPRequestHandler):
    """Ollama (`/api/tags`) and LM Studio (`/v1/models`, `/v1/chat/completions`) in one."""

    models: list[str]
    seen: Seen

    def log_message(self, *args: object) -> None:
        pass

    def _send(self, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/api/tags":
            self._send({"models": [{"name": m} for m in self.models]})
        elif self.path == "/v1/models":
            self._send({"data": [{"id": m} for m in self.models]})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).seen.append({"path": self.path, "body": body})
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        message = {"role": "assistant", "content": json.dumps({"ok": True})}
        self._send({
            "id": "x", "object": "chat.completion", "created": 1, "model": body["model"],
            "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })  # fmt: skip


def serve(models: list[str]) -> Iterator[tuple[str, Seen]]:
    handler = type("Handler", (FakeLocalAI,), {"models": models, "seen": []})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", handler.seen
    server.shutdown()
    server.server_close()


@pytest.fixture
def fake_ollama() -> Iterator[tuple[str, Seen]]:
    yield from serve(["llama3.1:8b", "qwen3"])


@pytest.fixture
def fake_lmstudio() -> Iterator[tuple[str, Seen]]:
    yield from serve(["gemma-3"])


def dead_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{s.getsockname()[1]}"


def point_probes(monkeypatch: pytest.MonkeyPatch, ollama: str, lmstudio: str) -> None:
    monkeypatch.setattr(routes, "LOCAL_SERVERS", {
        "ollama": (f"{ollama}/api/tags", "models", "name"),
        "lmstudio": (f"{lmstudio}/v1/models", "data", "id"),
    })  # fmt: skip


def save_pick(client: TestClient, pick: dict[str, str]) -> None:
    cfg = client.get("/api/search").json()
    cfg["ai"] = pick
    assert client.put("/api/search", json=cfg, headers=SAME_ORIGIN).status_code == 200


def test_scan_lists_running_servers_and_their_models(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    fake_ollama: tuple[str, Seen],
    fake_lmstudio: tuple[str, Seen],
) -> None:
    point_probes(monkeypatch, fake_ollama[0], fake_lmstudio[0])
    assert client.get("/api/ai/local").json() == {
        "ollama": {"running": True, "models": ["llama3.1:8b", "qwen3"]},
        "lmstudio": {"running": True, "models": ["gemma-3"]},
    }


def test_scan_reports_a_server_that_is_not_running(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_lmstudio: tuple[str, Seen]
) -> None:
    point_probes(monkeypatch, dead_url(), fake_lmstudio[0])
    got = client.get("/api/ai/local").json()
    assert got["ollama"] == {"running": False, "models": []}
    assert got["lmstudio"] == {"running": True, "models": ["gemma-3"]}


def test_pick_is_checked_then_saved(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, fake_lmstudio: tuple[str, Seen]
) -> None:
    base, seen = fake_lmstudio
    point_probes(monkeypatch, dead_url(), base)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    model = client.get("/api/ai/local").json()["lmstudio"]["models"][0]

    pick = {"provider": "litellm", "model": f"openai/{model}", "api_base": f"{base}/v1"}
    checked = client.post("/api/ai/check", json=pick, headers=SAME_ORIGIN).json()
    assert checked["ok"] is True and "openai/gemma-3" in checked["message"], checked
    assert [r["path"] for r in seen] == ["/v1/chat/completions"]  # one tiny round trip
    assert seen[0]["body"]["model"] == "gemma-3"

    assert client.get("/api/status").json()["ai_ready"] is False
    save_pick(client, pick)
    assert client.get("/api/search").json()["ai"] == pick
    ai = client.get("/api/ai").json()
    assert (ai["provider"], ai["model"]) == ("litellm", f"openai/{model}")
    assert client.get("/api/status").json()["ai_ready"] is True


def test_ollama_pick_is_saved_with_its_base_url(
    client: TestClient, fake_ollama: tuple[str, Seen]
) -> None:
    pick = {"provider": "litellm", "model": "ollama/llama3.1:8b", "api_base": fake_ollama[0]}
    save_pick(client, pick)
    assert client.get("/api/search").json()["ai"] == pick
    assert client.get("/api/ai").json()["model"] == "ollama/llama3.1:8b"


# --- opt-in: the real local servers on this machine ---

live_ollama = os.environ.get("LINKIT_LIVE_OLLAMA") == "1"
live_lmstudio = os.environ.get("LINKIT_LIVE_LMSTUDIO") == "1"
LIVE_PICKS = {
    "ollama": ("ollama/{}", "http://127.0.0.1:11434"),
    "lmstudio": ("openai/{}", "http://127.0.0.1:1234/v1"),
}


@pytest.mark.live
@pytest.mark.skipif(
    not (live_ollama or live_lmstudio),
    reason="set LINKIT_LIVE_OLLAMA=1 and/or LINKIT_LIVE_LMSTUDIO=1 (a running local server)",
)
def test_live_local_server_scan_and_tiny_check(client: TestClient) -> None:
    found = client.get("/api/ai/local").json()
    names = [n for n, on in (("ollama", live_ollama), ("lmstudio", live_lmstudio)) if on]
    for name in names:
        assert found[name]["running"] and found[name]["models"], f"{name}: not running or no models"
        template, base = LIVE_PICKS[name]
        pick = {"provider": "litellm", "model": template.format(found[name]["models"][0]),
                "api_base": base}  # fmt: skip
        r = client.post("/api/ai/check", json=pick, headers=SAME_ORIGIN).json()
        assert r["ok"] is True, r
