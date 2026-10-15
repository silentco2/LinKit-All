import asyncio
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from linkit_all.core.db import init_db
from linkit_all.core.log import redact
from linkit_all.providers import ProviderError, UsageLimitError, claude_cli, codex_cli
from linkit_all.providers.base import LLMProvider, extract_json


class Answer(BaseModel):
    score: int


class Fake(LLMProvider):
    name = "fake"

    def __init__(self, replies: list[str], **kw: object) -> None:
        super().__init__("fake-model", **kw)  # type: ignore[arg-type]
        self.replies = replies
        self.prompts: list[str] = []

    async def _call(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.replies.pop(0)


def test_extract_json_strips_fences_and_prose() -> None:
    assert extract_json('Sure!\n```json\n{"score": 7}\n```') == '{"score": 7}'
    assert extract_json('Here: {"score": 7} done') == '{"score": 7}'


def test_complete_includes_schema_and_validates() -> None:
    p = Fake(['{"score": 9}'])
    assert asyncio.run(p.complete("rate it", Answer)).score == 9
    assert "rate it" in p.prompts[0] and '"score"' in p.prompts[0]


def test_retries_invalid_output_then_succeeds() -> None:
    p = Fake(["not json", '{"score": "x"}', '{"score": 3}'])
    assert asyncio.run(p.complete("q", Answer)).score == 3
    assert len(p.prompts) == 3
    assert "did not validate" in p.prompts[1]


def test_gives_up_after_max_retries() -> None:
    p = Fake(["bad"] * 3)
    with pytest.raises(ProviderError, match="after 3 attempts"):
        asyncio.run(p.complete("q", Answer))


def test_cache_hit_skips_call(tmp_path: Path) -> None:
    db = init_db(tmp_path / "t.db")
    asyncio.run(Fake(['{"score": 5}'], cache=db).complete("q", Answer))
    p = Fake([], cache=db)
    assert asyncio.run(p.complete("q", Answer)).score == 5
    assert p.prompts == []


def test_claude_parse_output() -> None:
    ok = json.dumps({"type": "result", "is_error": False, "result": '{"ok": true}'})
    assert claude_cli.parse_output(0, ok, "") == '{"ok": true}'
    limited = json.dumps({"is_error": True, "result": "Claude AI usage limit reached|1760000000"})
    with pytest.raises(UsageLimitError):
        claude_cli.parse_output(1, limited, "")
    with pytest.raises(ProviderError):
        claude_cli.parse_output(1, "", "Invalid API key · Please run /login")


def test_codex_parse_output() -> None:
    assert codex_cli.parse_output(0, "", "", '{"ok": true}') == '{"ok": true}'
    events = "\n".join(
        [
            json.dumps({"type": "thread.started"}),
            json.dumps(
                {"type": "turn.failed", "error": {"message": "You've hit your usage limit."}}
            ),
        ]
    )
    with pytest.raises(UsageLimitError):
        codex_cli.parse_output(1, events, "", "")
    with pytest.raises(ProviderError, match="not logged in"):
        codex_cli.parse_output(1, "", "not logged in", "")


def test_redact_secrets() -> None:
    line = 'password=hunter2 api_key: "abc123" Authorization: Bearer xyz.token sk-ABCDEFGH12345678'
    out = redact(line)
    for secret in ("hunter2", "abc123", "xyz.token", "ABCDEFGH12345678"):
        assert secret not in out
    assert "password=***" in out
