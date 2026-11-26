"""Free models: fallback order through a fake OpenAI-compatible server (no live calls)."""

import asyncio
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from loguru import logger
from pydantic import BaseModel

from linkit_all.core.config import FreeKey, Settings
from linkit_all.core.search import SearchConfig
from linkit_all.pipeline import ai_settings
from linkit_all.providers import ProviderError, UsageLimitError, get_provider, litellm_api
from linkit_all.providers.free import PRESETS, FreePreset

KEY_A, KEY_B = "sk-free-aaaa-1234567890", "sk-free-bbbb-0987654321"


class Answer(BaseModel):
    score: int


class Fake:
    """Per provider path ("/a", "/b"): queued replies, (status, content); the last one repeats."""

    def __init__(self) -> None:
        self.script: dict[str, list[tuple[int, str]]] = {}
        self.hits: list[str] = []


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[Fake]:
    state = Fake()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            self.rfile.read(int(self.headers.get("content-length") or 0))
            who = self.path.split("/")[1]
            state.hits.append(who)
            queue = state.script[who]
            status, content = queue.pop(0) if len(queue) > 1 else queue[0]
            body = (
                {
                    "id": "x",
                    "object": "chat.completion",
                    "created": 0,
                    "model": "m",
                    "choices": [
                        {
                            "index": 0,
                            "finish_reason": "stop",
                            "message": {"role": "assistant", "content": content},
                        }
                    ],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
                if status == 200
                else {"error": {"message": content, "type": "error", "code": status}}
            )
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_port}"
    presets = {
        pid: FreePreset(pid, pid.upper(), "openai/m", "", "", "", False, f"{base}/{pid}/v1")
        for pid in ("a", "b")
    }
    monkeypatch.setattr(litellm_api, "BY_ID", presets)
    monkeypatch.setattr(litellm_api, "REST_S", 0.2)  # tests that need longer set it
    yield state
    server.shutdown()


def provider(*ids: str) -> litellm_api.FreeProvider:
    keys = {"a": KEY_A, "b": KEY_B}
    return litellm_api.FreeProvider([FreeKey(id=i, key=keys[i]) for i in ids])


def ask(p: litellm_api.FreeProvider) -> int:
    return asyncio.run(p.complete("rate it", Answer, use_cache=False)).score


def test_first_provider_answers(fake: Fake) -> None:
    fake.script = {"a": [(200, '{"score": 7}')], "b": [(200, '{"score": 1}')]}
    assert ask(provider("a", "b")) == 7
    assert fake.hits == ["a"]


def test_limit_moves_to_next_and_rests_the_first(
    fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake.script = {"a": [(429, "Rate limit reached")], "b": [(200, '{"score": 5}')]}
    monkeypatch.setattr(litellm_api, "REST_S", 60.0)
    p = provider("a", "b")
    assert ask(p) == 5
    assert ask(p) == 5  # "a" is resting: not asked again
    assert [h for h in fake.hits if h == "a"] == ["a"]


def test_outage_moves_to_next(fake: Fake) -> None:
    fake.script = {"a": [(503, "Service Unavailable")], "b": [(200, '{"score": 4}')]}
    assert ask(provider("a", "b")) == 4


def test_all_exhausted_pauses(fake: Fake) -> None:
    fake.script = {"a": [(429, "Rate limit reached")], "b": [(503, "overloaded")]}
    with pytest.raises(UsageLimitError, match="Free models usage limit reached"):
        ask(provider("a", "b"))
    assert fake.hits == ["a", "b", "a", "b"]  # one wait for per-minute limits, then pause


def test_bad_json_is_retried(fake: Fake) -> None:
    fake.script = {"a": [(200, "not json"), (200, '{"score": 9}')]}
    assert ask(provider("a")) == 9
    assert fake.hits == ["a", "a"]


def test_order_is_the_users(fake: Fake) -> None:
    fake.script = {"a": [(200, '{"score": 1}')], "b": [(200, '{"score": 2}')]}
    assert ask(provider("b", "a")) == 2


def test_check_reports_each_provider(fake: Fake) -> None:
    fake.script = {"a": [(200, '{"ok": true}')], "b": [(200, "never json")]}
    msg = asyncio.run(provider("a", "b").check())
    assert "A: ok" in msg and "B: not working" in msg
    fake.script = {"a": [(401, "invalid api key")], "b": [(200, "never json")]}
    with pytest.raises(ProviderError):
        asyncio.run(provider("a", "b").check())


def test_keys_never_in_logs_or_errors(fake: Fake) -> None:
    lines: list[str] = []
    sink = logger.add(lines.append, level="DEBUG")
    fake.script = {"a": [(401, f"invalid api key {KEY_A}")], "b": [(400, f"bad {KEY_B}")]}
    try:
        with pytest.raises(ProviderError) as e:
            ask(provider("a", "b"))
        with pytest.raises(ProviderError) as e2:
            asyncio.run(provider("a", "b").check())
    finally:
        logger.remove(sink)
    text = "".join(lines) + str(e.value) + str(e2.value)
    assert KEY_A not in text and KEY_B not in text


def test_disabled_or_blank_keys_are_skipped() -> None:
    with pytest.raises(ProviderError, match="add a key"):
        litellm_api.FreeProvider([FreeKey(id="groq", key=" "), FreeKey(id="x", key="k")])
    p = litellm_api.FreeProvider([FreeKey(id="groq", key=KEY_A, enabled=False),
                                  FreeKey(id="mistral", key=KEY_B)])  # fmt: skip
    assert [pid for pid, _ in p.subs] == ["mistral"]


def test_cloudflare_needs_its_account_id() -> None:
    with pytest.raises(ProviderError, match="account ID"):
        litellm_api.FreeProvider([FreeKey(id="cloudflare", key=KEY_A)])
    p = litellm_api.FreeProvider([FreeKey(id="cloudflare", key=KEY_A, account_id="abc")])
    assert p.subs[0][1].api_base == ("https://api.cloudflare.com/client/v4/accounts/abc/ai/v1")


def test_saved_choice_reaches_get_provider() -> None:
    cfg = SearchConfig.model_validate(
        {"ai": {"provider": "free", "free_keys": [{"id": "groq", "key": KEY_A}]}}
    )
    p = get_provider(ai_settings(Settings(), cfg))
    assert isinstance(p, litellm_api.FreeProvider)
    assert KEY_A not in repr(ai_settings(Settings(), cfg))
    other = SearchConfig.model_validate({"ai": {"provider": "litellm", "model": "x/y",
                                                "free_keys": [{"id": "groq", "key": KEY_A}]}})  # fmt: skip
    assert ai_settings(Settings(), other).free_keys == []


def test_presets_are_complete() -> None:
    for p in PRESETS:
        assert p.key_url.startswith("https://") and p.terms_url.startswith("https://")
        assert p.limits and "/" in p.model
        assert p.needs_account == ("{account_id}" in p.api_base)
