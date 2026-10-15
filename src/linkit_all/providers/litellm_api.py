"""API keys and local OpenAI-compatible servers (Ollama, LM Studio) through LiteLLM."""

from typing import Any

from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError, classify


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
        self.api_key = api_key
        self.api_base = api_base

    async def _call(self, prompt: str) -> str:
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
            raise UsageLimitError(str(e)) from e
        except Exception as e:
            raise classify(f"{type(e).__name__}: {e}") from e
        return str(resp.choices[0].message.content or "")
