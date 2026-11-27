---
title: Free AI models
description: "Run LinKit All on free API tiers from Groq, Cloudflare Workers AI, Z.AI and OpenRouter: limits, how to get each key, what each provider does with your data, and how the fallback works."
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

Limits and terms were checked on **2026-11-26** (Z.AI on 2026-11-27) on each provider's own pages. Providers change
them often: the provider's page is always right over this one.

| Provider | Model LinKit uses | Free limits | Trains on what you send? | Get a key |
|---|---|---|---|---|
| Groq | `openai/gpt-oss-120b` | About 30 requests a minute, 1,000 a day, 200K tokens a day | No. Its services agreement says Groq may not use inputs or outputs for training. Logs can be kept up to 30 days for reliability and abuse checks. | [console.groq.com/keys](https://console.groq.com/keys) |
| Cloudflare Workers AI | `@cf/meta/llama-3.3-70b-instruct-fp8-fast` | 10,000 Neurons a day (about 50K output tokens on this model), reset at 00:00 UTC | No. Cloudflare says it does not use Workers AI content to train models. | [API tokens](https://dash.cloudflare.com/profile/api-tokens), plus your account ID |
| Z.AI | `glm-4.5-flash` | Free model; Z.AI publishes no request or token limits for it | No. Its API terms say Z.AI will not use API content to improve its services unless you agree, and does not store it. | [z.ai API keys](https://z.ai/manage-apikey/apikey-list) |
| OpenRouter | `google/gemma-4-31b-it:free` | 20 requests a minute, 50 a day (1,000 a day once you have bought $10 of credits) | May. It depends on the model's host; OpenRouter's terms say some models may store or train on inputs. | [openrouter.ai/keys](https://openrouter.ai/keys) |

Terms: [Groq](https://console.groq.com/docs/legal/services-agreement) ·
[Cloudflare](https://developers.cloudflare.com/workers-ai/platform/data-usage/) ·
[Z.AI](https://docs.z.ai/legal-agreement/terms-of-use) ·
[OpenRouter](https://openrouter.ai/docs/features/privacy-and-logging).

Z.AI is a Singapore company (JINGSHENG HENGXING TECHNOLOGY PTE. LTD.) and processes API data in
Singapore.

### Left out, and why

| Provider | Reason (2026-11-26) |
|---|---|
| Mistral | Since 2026-11-27 its free plan answers "You need a subscription to access this API". |
| LLM7 | No published free limits, privacy policy or terms could be found. |
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

## How far the free limits go

Measured on 2026-11-27 with real prompts (a real CV and real job ads) on Cloudflare's Llama 3.3
70B. Other models count tokens a little differently. Groq's `gpt-oss-120b` also writes hidden
reasoning, which counts as output: LinKit asks it for low reasoning, which keeps its output
within about 1.5 times the table's numbers (by default it was 5 to 10 times more).

| AI call | Tokens in | Tokens out | How often |
|---|---|---|---|
| Score a batch of 15 jobs | 9,400 | 3,000 | once per 15 jobs the AI scores (default 100 jobs: 7 calls) |
| Score a batch of 6 jobs (with Groq on the list) | 5,000 | 1,200 | once per 6 jobs (100 jobs: 17 calls) |
| Tailor the CV | 3,000 | 100–250 | once per application |
| Answer screening questions (5) | 3,100 | 160 | about once per application |
| Read a form page | 1,300 | 350 | about 4 per application on sites without a handler |
| Cover letter | 2,500 | 120 | only when the form has a cover letter box |

Finding, filtering and ranking jobs use no AI. In round numbers:

- **Scoring 100 jobs:** about 83K tokens (63K in, 20K out).
- **One application:** about 13.5K tokens (11.7K in, 1.8K out).
- **A full run** (100 jobs scored, 25 applications): about 420K tokens.

What one day of each free tier covers:

| Provider | Daily allowance | One day covers |
|---|---|---|
| Cloudflare | 10,000 Neurons (scoring 100 jobs costs about 5,750; one application about 670) | 100 jobs scored and about 6 applications |
| Groq | 200K tokens, at most 8K tokens a minute | 100 jobs scored and about 6 applications. Groq allows 8K tokens a minute, so with Groq on the list LinKit sends 6 jobs per score call instead of 15. Within a minute, the next call goes to the next provider. |
| Z.AI | No published limit | Not measured yet |
| Groq and Cloudflare together | | 100 jobs scored and about 20 applications |

A real practice run on 2026-11-27 with Groq, Cloudflare and Z.AI: 20,334 new jobs found,
215 passed the filters, all 215 scored in 13 minutes, then 25 practice applications. AI use:
Groq 81K tokens (it hit its per-minute limit 13 times; the next provider answered each time),
Cloudflare 186K tokens (about 9,600 Neurons, nearly its whole day), Z.AI 14K tokens. The run
finished without pausing.

So one search a day (find, rank and score 100 jobs) fits in either free tier alone. Applying is
the expensive part. For more applications a day, add a third provider or lower **Applying >
applications per run**.

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
