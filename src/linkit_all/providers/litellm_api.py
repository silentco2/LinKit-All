"""API keys and local OpenAI-compatible servers (Ollama, LM Studio) through LiteLLM."""

import functools
import os
from pathlib import Path
from typing import Any

from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError, classify

# No network call for LiteLLM's price list (rule: no traffic beyond the chosen provider).
# Set before any litellm import; this module is the only place that imports it.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOCAL_ANTHROPIC_BETA_HEADERS", "True")


@functools.cache
def _preload_tokenizer() -> None:
    """LiteLLM loads tiktoken's cl100k_base for every non-OpenAI model, and its own tokenizers
    folder lacks it, so tiktoken would download it. Load it once from the copy we ship (tiktoken
    checks its pinned sha256); LiteLLM then finds it in memory and keeps its folder for o200k.
    Always runs, because LiteLLM overwrites TIKTOKEN_CACHE_DIR anyway; the old value is restored."""
    path = Path(__file__).parent / "tiktoken_cache"
    if not (path / "9b5ad71b2ce5302211f9c61530b329a4922fc6a4").is_file():
        return  # never let tiktoken download here
    import tiktoken

    old = os.environ.get("TIKTOKEN_CACHE_DIR")
    os.environ["TIKTOKEN_CACHE_DIR"] = str(path)
    try:
        tiktoken.get_encoding("cl100k_base")
    finally:
        if old is None:
            os.environ.pop("TIKTOKEN_CACHE_DIR", None)
        else:
            os.environ["TIKTOKEN_CACHE_DIR"] = old


class LiteLLMProvider(LLMProvider):
    name = "litellm"

    def __init__(
        self,
        model: str | None,
        *,
        api_key: str | None = None,
        api_base: str | None = None,
        **kwargs: Any,
    ) -> None:
        if not model:
            raise ProviderError("litellm needs a model, e.g. LINKIT_MODEL=openai/gpt-5-mini")
        super().__init__(model, **kwargs)
        # Local OpenAI-compatible servers ignore the key, but the OpenAI client insists on one.
        self.api_key = api_key or (
            "local" if api_base and not os.environ.get("OPENAI_API_KEY") else None
        )
        self.api_base = api_base

    async def _call(self, prompt: str) -> str:
        _preload_tokenizer()
        # Slow imports, only paid when this provider is used.
        import litellm
        from litellm.exceptions import RateLimitError

        try:
            resp: Any = await litellm.acompletion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                api_key=self.api_key,
                api_base=self.api_base,
                response_format={"type": "json_object"},
                drop_params=True,  # models without JSON mode just ignore it
                num_retries=2,
                timeout=self.timeout_s,
            )
        except RateLimitError as e:
            raise UsageLimitError(str(e), self.name) from e
        except Exception as e:
            raise classify(f"{type(e).__name__}: {e}", self.name) from e
        return str(resp.choices[0].message.content or "")
