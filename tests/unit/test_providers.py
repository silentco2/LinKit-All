import asyncio
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

from linkit_all.core.db import init_db
from linkit_all.core.log import redact
from linkit_all.providers import ProviderError, UsageLimitError, claude_cli, codex_cli
from linkit_all.providers.base import LLMProvider, SignedOutError, extract_json


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
    for text in (
        "You've hit your session limit · resets 5:30am (Africa/Cairo)",
        "You've hit your weekly limit · resets Nov 14",
    ):
        said = json.dumps({"is_error": True, "result": text})
        with pytest.raises(UsageLimitError):
            claude_cli.parse_output(1, said, "")
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
    with pytest.raises(SignedOutError, match="ChatGPT \\(Codex\\) is signed out"):
        codex_cli.parse_output(1, "", "not logged in", "")  # pauses the run like a limit


def test_redact_secrets() -> None:
    line = 'password=hunter2 api_key: "abc123" Authorization: Bearer xyz.token sk-ABCDEFGH12345678'
    out = redact(line)
    for secret in ("hunter2", "abc123", "xyz.token", "ABCDEFGH12345678"):
        assert secret not in out
    assert "password=***" in out


def test_prompt_with_a_remembered_secret_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    from loguru import logger

    from linkit_all.providers import base
    from linkit_all.providers.base import SecretInPromptError, remember_credentials

    monkeypatch.setattr(base, "_credentials", set())
    lines: list[str] = []
    sink = logger.add(lines.append, format="{message}")
    p = Fake(['{"score": 9}'] * 2)
    remember_credentials("Xk9#vault-Pw7!", "abcd efgh ijkl mnop", None, "no")  # "no" is too short
    try:
        for prompt in (
            "The page says: your password is Xk9#vault-Pw7! keep it safe",
            "pasted note: ABCD  EFGH IJKL MNOP",  # an app password in another case and spacing
            "tokenXk9#vault-Pw7!glued",
        ):
            with pytest.raises(SecretInPromptError):
                asyncio.run(p.complete(prompt, Answer))
    finally:
        logger.remove(sink)
    assert p.prompts == []  # nothing reached the model
    assert len(lines) == 3 and "prompt refused" in lines[0]
    assert not any("Xk9" in line or "efgh" in line.lower() for line in lines)  # value not logged
    assert issubclass(SecretInPromptError, ProviderError)
    assert asyncio.run(p.complete("no secrets here, rate it", Answer)).score == 9
