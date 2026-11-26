---
title: Free AI models
description: "Run LinKit All on free API tiers from Groq, Cloudflare Workers AI, Mistral and OpenRouter: limits, how to get each key, what each provider does with your data, and how the fallback works."
---

# Free AI models

LinKit All can run on the free API tiers of a few AI providers instead of a paid plan or API
key. Paste one or more free keys in **Settings > AI > Free models** (or on the first-run AI
step). LinKit asks the first provider in your list; when it reaches a limit, has a bad key or
is down, the next one answers.

!!! warning "Your CV leaves this computer"
    Free providers receive your CV text and the job texts, just like any other AI you choose.
    Each provider you add receives them. Some free tiers may keep or train on what you send:
    those are marked in the app and in the table below. Your answers to
    [sensitive questions](action-center.md#sensitive-questions) never reach any AI.

## The providers

Limits and terms were checked on **2026-11-26** on each provider's own pages. Providers change
them often: the provider's page is always right over this one.

| Provider | Model LinKit uses | Free limits | Trains on what you send? | Get a key |
|---|---|---|---|---|
| Groq | `openai/gpt-oss-120b` | About 30 requests a minute, 1,000 a day, 200K tokens a day | No. Its services agreement says Groq may not use inputs or outputs for training. Logs can be kept up to 30 days for reliability and abuse checks. | [console.groq.com/keys](https://console.groq.com/keys) |
| Cloudflare Workers AI | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | 10,000 Neurons a day (about 50K output tokens on this model), reset at 00:00 UTC | No. Cloudflare says it does not use Workers AI content to train models. | [API tokens](https://dash.cloudflare.com/profile/api-tokens), plus your account ID |
| Mistral | `mistral-small-latest` | Shown in the Mistral console | May. The free plan has a training opt-out in the console. | [console.mistral.ai/api-keys](https://console.mistral.ai/api-keys) |
| OpenRouter | `google/gemma-4-31b-it:free` | 20 requests a minute, 50 a day (1,000 a day once you have bought $10 of credits) | May. It depends on the model's host; OpenRouter's terms say some models may store or train on inputs. | [openrouter.ai/keys](https://openrouter.ai/keys) |

Terms: [Groq](https://console.groq.com/docs/legal/services-agreement) ·
[Cloudflare](https://developers.cloudflare.com/workers-ai/platform/data-usage/) ·
[Mistral](https://legal.mistral.ai/terms) ·
[OpenRouter](https://openrouter.ai/docs/features/privacy-and-logging).

The Mistral limits and terms pages could not be read on the date above, so its row is less
certain than the others.

### Left out, and why

| Provider | Reason (2026-11-26) |
|---|---|
| Google Gemini (AI Studio free tier) | Its terms say not to submit personal information to the unpaid service. A CV is personal information. |
| NVIDIA NIM (build.nvidia.com) | Trial terms: no personal information, internal testing and evaluation only, not production. |
| GitHub Models | Retired on July 30, 2026. |
| Cerebras | No lasting free tier: a $5 trial credit that expires after 30 days. |
| Hugging Face Inference Providers | Free accounts get no monthly credits. |
| SambaNova Cloud | Free tier is 20 requests a day, and its models are for evaluation only. |
| Cohere | Trial keys are 1,000 calls a month and meant for evaluation. |

## Set it up

1. Open **Settings > AI** and pick **Free models**.
2. For each provider you want, press **Get a free key**, sign up on the provider's site and
   create a key. Cloudflare also needs your account ID (it is on the right of your Cloudflare
   dashboard home page).
3. Paste the key. LinKit tests every provider you added and saves the list when at least one
   works.
4. Order the list with the arrows. Untick **Use** to keep a key but skip that provider.

Keys are stored with your search settings on this computer and shown masked. They are never
written to the logs.

To test from the command line:

```text
linkit ai-check
```

It tests each provider on your list on its own, prints `ok` or `not working (reason)` for each,
and fails only when none works.

## How the fallback works

- Each AI call goes to the first provider on your list that is not resting.
- A provider that answers "limit reached" (HTTP 429), has a bad key, or is down (HTTP 502,
  503, 504 or a timeout) rests for one minute, and the next provider answers instead.
- When every provider is resting, LinKit waits for the first to wake and tries each one once
  more. If they all fail again, the run pauses with "Free models usage limit reached", the same
  way it pauses when a paid plan runs out. Jobs keep their state, and the run continues once
  you resume it.
- An answer that is not valid JSON is asked again (2 more times), as with every provider.

Free models fail the JSON format more often than paid ones. If `linkit ai-check` shows one
provider as not working with "invalid output", move it to the end of the list or untick it.
