import pytest

from linkit_all.core.config import Settings
from linkit_all.core.search import SearchConfig
from linkit_all.pipeline import ai_settings

BASE = "http://127.0.0.1:1234/v1"


def cfg(provider: str, api_base: str | None = BASE) -> SearchConfig:
    return SearchConfig.model_validate(
        {"ai": {"provider": provider, "model": "openai/gemma-3", "api_base": api_base}}
    )


def test_api_base_applies_to_litellm() -> None:
    s = ai_settings(Settings(), cfg("litellm"))
    assert (s.provider, s.model, s.api_base) == ("litellm", "openai/gemma-3", BASE)


@pytest.mark.parametrize("provider", ["codex_cli", "claude_cli"])
def test_api_base_ignored_for_cli_providers(provider: str) -> None:
    assert ai_settings(Settings(), cfg(provider)).api_base is None


def test_env_api_base_kept_when_wizard_has_none() -> None:
    env = Settings(api_base="http://localhost:9/v1")
    assert ai_settings(env, cfg("litellm", None)).api_base == "http://localhost:9/v1"
