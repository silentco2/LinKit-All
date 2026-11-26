"""Providers with a free API tier, called through LiteLLM (CLAUDE.md §2: with free providers,
CV/job text goes to each free provider the user adds). Data only.

Checked 2026-11-26 against each provider's own pricing, limits and terms pages (docs/free-ai.md).
Dropped then: Gemini and NVIDIA (free terms forbid personal data, and a CV is personal data),
Cerebras and Hugging Face (no lasting free tier), GitHub Models (retired July 2026), SambaNova
and Cohere (evaluation only, 20 requests/day or 1,000/month).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FreePreset:
    id: str
    label: str
    model: str  # LiteLLM model name
    key_url: str
    terms_url: str
    limits: str  # as the provider stated them on the date above
    trains_on_data: bool  # the free tier may keep or train on prompts
    api_base: str = ""  # "{account_id}" is filled from the user's entry
    needs_account: bool = False  # Cloudflare: account ID besides the token


# Default fallback order: providers that never train on prompts first.
PRESETS: tuple[FreePreset, ...] = (
    FreePreset(
        "groq",
        "Groq",
        "groq/openai/gpt-oss-120b",
        "https://console.groq.com/keys",
        "https://console.groq.com/docs/legal/services-agreement",
        "About 30 requests a minute, 1,000 a day, 200K tokens a day.",
        trains_on_data=False,
    ),
    FreePreset(
        "cloudflare",
        "Cloudflare Workers AI",
        "openai/@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "https://dash.cloudflare.com/profile/api-tokens",
        "https://developers.cloudflare.com/workers-ai/platform/data-usage/",
        "10,000 Neurons a day (about 50K output tokens on this model), reset at 00:00 UTC.",
        trains_on_data=False,
        api_base="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        needs_account=True,
    ),
    FreePreset(
        "mistral",
        "Mistral",
        "mistral/mistral-small-latest",
        "https://console.mistral.ai/api-keys",
        "https://legal.mistral.ai/terms",
        "Free plan limits are shown in the Mistral console.",
        trains_on_data=True,  # free plan: training opt-out available in the console
    ),
    FreePreset(
        "openrouter",
        "OpenRouter (free models)",
        "openrouter/google/gemma-4-31b-it:free",
        "https://openrouter.ai/keys",
        "https://openrouter.ai/docs/features/privacy-and-logging",
        "20 requests a minute, 50 a day (1,000 a day once you have bought $10 of credits).",
        trains_on_data=True,  # "Some Models may store or train on your Inputs."
    ),
)

BY_ID: dict[str, FreePreset] = {p.id: p for p in PRESETS}
