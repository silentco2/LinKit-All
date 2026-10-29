"""Drive the real Angular UI: the real FastAPI app under uvicorn on a free port, a headless
Chrome (else Playwright's Chromium), fakes in the server process (it runs in this process).

Needs the built frontend: `cd frontend && npx ng build`. Without it every test here skips, which
is what happens in the Python CI job (the frontend is built in its own job).
"""

import sys
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import keyring
import pytest
import uvicorn
from playwright.sync_api import Browser, Page, sync_playwright

sys.path.insert(0, str(Path(__file__).parents[2] / "unit"))
from test_local_model_pick import point_probes, serve
from test_vault import MemoryKeyring

from linkit_all.api import app as app_module
from linkit_all.api import routes
from linkit_all.api.app import create_app
from linkit_all.core.config import Settings
from linkit_all.core.tools import chrome_path

NOT_BUILT = "run `cd frontend && npx ng build` first"


@dataclass
class UI:
    page: Page
    base_url: str
    console_errors: list[str]


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    if not (app_module.STATIC / "index.html").is_file():
        pytest.skip(NOT_BUILT)
    with sync_playwright() as pw:
        kw: dict[str, Any] = {"channel": "chrome"} if chrome_path() else {}
        if not kw and not Path(pw.chromium.executable_path).is_file():
            pytest.skip("no Chrome or Playwright Chromium (`playwright install chromium`)")
        b = pw.chromium.launch(headless=True, args=["--no-proxy-server"], **kw)
        yield b
        b.close()


@pytest.fixture(autouse=True)
def _mem_keyring() -> Iterator[None]:
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    yield
    keyring.set_keyring(previous)


@pytest.fixture
def fake_local_ai(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fake Ollama + LM Studio for the local-model scan, and a stub for `/api/ai/check`: the UI
    saves the fixed default addresses (:11434 / :1234), which no fake server listens on."""
    from linkit_all import providers

    class Checked:
        async def check(self) -> str:
            return "Fake local model answered."

        async def complete(self, prompt: str, schema: Any, **kw: Any) -> Any:
            return schema()  # screen 3 asks the model to fill gaps: nothing to add

    monkeypatch.setattr(providers, "get_provider", lambda *a, **k: Checked())
    # no CLI "found on this computer": else step 2 auto-tests the first one and moves on by itself
    monkeypatch.setattr(routes, "shutil", SimpleNamespace(which=lambda name: None))
    ollama = serve(["llama3.1:8b", "qwen3"])
    lmstudio = serve(["gemma-3"])
    point_probes(monkeypatch, next(ollama)[0], next(lmstudio)[0])
    yield
    for s in (ollama, lmstudio):
        next(s, None)  # shuts the fake server down


@pytest.fixture
def base_url(tmp_path: Path) -> Iterator[str]:
    import socket

    app = create_app(Settings(data_dir=tmp_path / "data"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=2))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        assert thread.is_alive() and time.monotonic() < deadline, "server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True
    thread.join(timeout=15)
    sock.close()


@pytest.fixture
def ui(browser: Browser, base_url: str) -> Iterator[UI]:
    context = browser.new_context(base_url=base_url)
    page = context.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.set_default_timeout(15_000)
    yield UI(page, base_url, errors)
    context.close()
