import hashlib
import os
import subprocess
import sys
from pathlib import Path

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


TOKENIZER = Path(__file__).parents[2] / "src/linkit_all/providers/tiktoken_cache"
CL100K_KEY = "9b5ad71b2ce5302211f9c61530b329a4922fc6a4"  # sha1 of the vocabulary URL
CL100K_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"  # tiktoken pin


def test_shipped_tokenizer_file_matches_tiktoken_pin() -> None:
    assert hashlib.sha256((TOKENIZER / CL100K_KEY).read_bytes()).hexdigest() == CL100K_SHA256


def test_preload_tokenizer_restores_users_cache_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    from linkit_all.providers import litellm_api

    monkeypatch.setenv("TIKTOKEN_CACHE_DIR", "user-dir")
    litellm_api._preload_tokenizer.cache_clear()
    litellm_api._preload_tokenizer()
    assert os.environ["TIKTOKEN_CACHE_DIR"] == "user-dir"


def test_litellm_default_tokenizer_loads_without_network() -> None:
    code = (
        "import socket\n"
        "def no(*a, **k): raise OSError('network blocked')\n"
        "socket.getaddrinfo = no\n"
        "socket.create_connection = no\n"
        "from linkit_all.providers import litellm_api\n"
        "litellm_api._preload_tokenizer()\n"
        "from litellm._lazy_imports import _get_default_encoding\n"
        "_get_default_encoding()\n"
    )
    env = {k: v for k, v in os.environ.items() if "TIKTOKEN" not in k}
    done = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True)  # noqa: S603
    assert done.returncode == 0, done.stderr[-800:]
