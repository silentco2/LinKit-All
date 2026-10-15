from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.config import Settings
from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError
from linkit_all.providers.claude_cli import ClaudeCLI
from linkit_all.providers.codex_cli import CodexCLI
from linkit_all.providers.litellm_api import LiteLLMProvider

__all__ = ["LLMProvider", "ProviderError", "UsageLimitError", "get_provider"]


def get_provider(settings: Settings, cache: sessionmaker[Session] | None = None) -> LLMProvider:
    c, t = settings.llm_concurrency, settings.llm_timeout_s
    match settings.provider:
        case "claude_cli":
            return ClaudeCLI(settings.model, concurrency=c, timeout_s=t, cache=cache)
        case "codex_cli":
            return CodexCLI(settings.model, concurrency=c, timeout_s=t, cache=cache)
        case "litellm":
            key = settings.api_key.get_secret_value() if settings.api_key else None
            return LiteLLMProvider(
                settings.model,
                api_key=key,
                api_base=settings.api_base,
                concurrency=c,
                timeout_s=t,
                cache=cache,
            )
