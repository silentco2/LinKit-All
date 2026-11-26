"""API keys and local OpenAI-compatible servers (Ollama, LM Studio) through LiteLLM."""

import asyncio
import functools
import os
import re
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from loguru import logger

from linkit_all.core.config import FreeKey
from linkit_all.providers.base import (
    LLMProvider,
    ProviderError,
    UsageLimitError,
    classify,
    remember_credentials,
    tidy,
)
from linkit_all.providers.free import BY_ID

# No network call from LiteLLM beyond the chosen provider: the price list, Anthropic beta headers,
# and HuggingFace tokenizer downloads (token_counter, llama/command-r names) use bundled copies.
# Set before any litellm import; this module is the only place that imports it.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("LITELLM_LOCAL_ANTHROPIC_BETA_HEADERS", "True")
os.environ.setdefault("LITELLM_OFFLINE_MODE", "True")


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
        num_retries: int = 2,
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
        self.num_retries = num_retries

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
                num_retries=self.num_retries,
                max_retries=self.num_retries,  # the OpenAI client's own retries
                timeout=self.timeout_s,
            )
        except RateLimitError as e:
            raise UsageLimitError(str(e), self.name) from e
        except Exception as e:
            raise classify(f"{type(e).__name__}: {e}", self.name) from e
        return str(resp.choices[0].message.content or "")


# A free provider that is down or slow is skipped like one that hit its limit.
_UNAVAILABLE = re.compile(
    r"(?i)50[234]|service.?unavailable|overloaded|timed? ?out|timeout|APIConnectionError"
)
# A provider that hit a limit rests this long; per-minute limits are over by then, a daily one
# costs one refused request a minute.
REST_S = 60.0


class FreeProvider(LLMProvider):
    """The user's free providers (providers/free.py) in their order: each call goes to the first
    one not resting; a limit, a bad key or an outage rests it and the next one answers. With all
    of them resting, UsageLimitError pauses the run like any plan limit.
    ponytail: a loop, not litellm.Router; the subs keep LiteLLMProvider's error mapping."""

    name = "free"

    def __init__(self, keys: Sequence[FreeKey], **kwargs: Any) -> None:
        super().__init__(None, **kwargs)
        chosen = [k for k in keys if k.enabled and k.key.strip() and k.id in BY_ID]
        if not chosen:
            raise ProviderError("Free models: add a key for at least one free provider")
        remember_credentials(*(k.key.strip() for k in chosen))
        self._keys = [k.key.strip() for k in chosen]
        self.subs: list[tuple[str, LiteLLMProvider]] = []
        for k in chosen:
            p = BY_ID[k.id]
            base = p.api_base.format(account_id=k.account_id.strip()) or None
            if p.needs_account and not k.account_id.strip():
                raise ProviderError(f"Free models: {p.label} needs its account ID")
            # no retries on the same provider: the next one is tried instead
            sub = LiteLLMProvider(p.model, api_key=k.key.strip(), api_base=base, num_retries=0)
            sub.timeout_s = self.timeout_s
            self.subs.append((p.id, sub))
        self._resting: dict[str, float] = {}

    def _hide(self, text: str) -> str:
        for key in self._keys:
            text = text.replace(key, "••••")
        return text

    async def _call(self, prompt: str) -> str:
        for attempt in range(2):
            now = time.monotonic()
            for pid, sub in self.subs:
                if self._resting.get(pid, 0.0) > now:
                    continue
                try:
                    return await sub._call(prompt)
                except UsageLimitError as e:  # includes a signed-out (bad) key
                    why = e.kind
                except ProviderError as e:
                    if not _UNAVAILABLE.search(str(e)):
                        raise ProviderError(self._hide(str(e))) from None
                    why = "unavailable"
                self._resting[pid] = time.monotonic() + REST_S
                logger.info("free models: {} {}, trying the next one", pid, why)
            if attempt == 0:  # all resting: wait once for the first to wake (per-minute limits)
                await asyncio.sleep(max(0.0, min(self._resting.values()) - time.monotonic()))
        raise UsageLimitError("", self.name)

    async def check(self) -> str:
        """Each enabled provider on its own: a JSON test prompt; fails only if none passes."""
        lines, passed = [], 0
        for pid, sub in self.subs:
            label = BY_ID[pid].label
            try:
                await sub.check()
                lines.append(f"{label}: ok")
                passed += 1
            except ProviderError as e:
                msg = e.message if isinstance(e, UsageLimitError) else tidy(str(e))
                lines.append(f"{label}: not working ({self._hide(msg)[:200]})")
        if not passed:
            raise ProviderError("; ".join(lines))
        return "Free models: " + "; ".join(lines)
