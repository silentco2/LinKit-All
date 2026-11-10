# Install

## What you need

- **Python 3.11 or newer.** [uv](https://docs.astral.sh/uv/) can install it for you.
- **LibreOffice**, to turn your CV into a PDF. Required for tailoring and applying.
- **[Chromium](https://www.chromium.org/getting-involved/download-chromium/)**, to apply to
  jobs. Not needed for finding and scoring jobs.

    !!! note "You may already have it"
        You do not need Chromium if you have Google Chrome, Microsoft Edge or Brave: LinKit
        All uses whichever it finds first. Edge comes with Windows, so on Windows there is
        nothing to install.
- **An AI provider.** See [AI providers](#ai-providers) below.
- **Tectonic**, only if your CV is a LaTeX file.

You do not need Node.js. The web page ships inside the Python package.

## Install LinKit All

```bash
uv tool install linkit-all
linkit doctor
```

!!! note "Not published yet"
    LinKit All has not been released on PyPI yet, so `uv tool install linkit-all` works
    only after the first release. Until then, run it from a source checkout. See
    [Development](development.md).

`linkit doctor` checks every outside tool and tells you what is missing. Each line starts
with `ok`, `MISSING` or `optional`:

```text
[ok] Python >= 3.11: ...
[ok] LibreOffice: ...
[ok] Chromium browser: ...
[optional] Codex CLI: npm i -g @openai/codex
[optional] Claude CLI: https://claude.com/claude-code
[optional] Tectonic: LaTeX CVs only: https://tectonic-typesetting.github.io
```

The command exits with an error only when a required tool (Python or LibreOffice) is missing.

Start the app with:

```bash
linkit
```

This opens the web page at `http://127.0.0.1:8765`. Use `linkit serve --port 9000 --no-open`
to change the port or to skip opening a browser.

## LibreOffice

LibreOffice turns your tailored CV into a PDF and lets LinKit All check that the layout did
not change. You have two choices.

=== "Install LibreOffice normally"

    Download it from [libreoffice.org](https://www.libreoffice.org/download/). LinKit All
    finds it on your PATH or in the usual install folders.

=== "Use the minimal bundle"

    The full Windows install is about 1.6 GB. The minimal bundle is about 439 MB
    (a 145 MB zip). It is built from an existing LibreOffice install by
    `scripts/bundle_libreoffice.py`. Install it into LinKit All's data folder with:

    ```bash
    linkit install-libreoffice path/to/libreoffice-minimal.zip
    ```

    The argument can be a zip file or a folder. The command checks that it contains
    `program/soffice.exe`, and refuses it if not. LinKit All uses this copy before any
    system install.

    You do not need to download it yourself on Windows (64-bit): the app offers an
    **Install it for me** button when LibreOffice is missing (a 145 MB download, about
    440 MB installed). It downloads the zip from the GitHub release
    `libreoffice-26.2.6-win-x64` of the project, checks its SHA-256 before unpacking, and
    installs it into the data folder.

    The bundle is for Windows x64 only. On macOS and Linux, install LibreOffice normally.

## Browser

LinKit All drives a Chromium browser you already have: Google Chrome first, else Microsoft
Edge, Brave or [Chromium](https://www.chromium.org/getting-involved/download-chromium/). It
does not download one. Each job site gets its own browser profile inside the
data folder, so logins and cookies are kept between runs and stay separate from your
everyday browsing. The LinkIt Fill extension goes in whichever browser you use day to day.

## Tectonic (LaTeX CVs only)

If your CV is a `.tex` file, install [Tectonic](https://tectonic-typesetting.github.io) and
make sure `tectonic` is on your PATH (or in `~/.cargo/bin`). Word, OpenDocument and PDF CVs
do not need it.

## AI providers

LinKit All sends prompts to one AI provider. You choose it in the [setup wizard](setup.md)
or with environment variables.

| Provider | `LINKIT_PROVIDER` | What you need |
|---|---|---|
| ChatGPT plan | `codex_cli` (default) | Codex CLI installed and signed in |
| Claude plan | `claude_cli` | Claude Code installed and signed in |
| API key | `litellm` | A model name and an API key |
| Local model | `litellm` | Ollama or LM Studio running on this computer |

Test any choice with:

```bash
linkit ai-check --provider codex_cli
```

### Codex CLI and Claude CLI

These use your own subscription.

!!! note "Plan limits"
    Usage counts against **your own plan limits**. LinKit All keeps this low: free local
    ranking happens first, jobs are scored 10 to 20 at a time, and answers are cached by
    prompt. When a limit is hit, the run **pauses** and continues the next time you start
    it. Vendors can change their plan rules, so check them yourself.

Sign in to the CLI in your own terminal first. LinKit All calls it from an empty temporary
folder with the CLI's own tools turned off, so the AI can only reply with text. One call
runs at a time by default (`LINKIT_LLM_CONCURRENCY`, 1 to 3).

### API keys

Set the model and key in your environment. LinKit All does not store the key.

=== "Windows (PowerShell)"

    ```powershell
    $env:LINKIT_PROVIDER = "litellm"
    $env:LINKIT_MODEL = "openai/gpt-5-mini"
    $env:LINKIT_API_KEY = "your-key"
    ```

=== "macOS / Linux"

    ```bash
    export LINKIT_PROVIDER=litellm
    export LINKIT_MODEL=openai/gpt-5-mini
    export LINKIT_API_KEY=your-key
    ```

If `LINKIT_API_KEY` is not set, the usual provider variables (such as `OPENAI_API_KEY`) are
used. Model names follow [LiteLLM](https://docs.litellm.ai/), so many providers work.

### Local models

Run Ollama or LM Studio, then pick **Local model** in the wizard's AI step. The wizard
scans for both and lists the models they have. You can also set it by hand:

| Server | `LINKIT_MODEL` | `LINKIT_API_BASE` |
|---|---|---|
| Ollama | `ollama/<model>` | `http://127.0.0.1:11434` |
| LM Studio | `openai/<model>` | `http://127.0.0.1:1234/v1` |

Nothing leaves your computer. Small models can score and tailor less accurately. Every
answer is checked against a strict format and asked again when it is invalid (up to two
more tries).

## Settings you can change

All environment settings use the `LINKIT_` prefix.

| Variable | Default | Meaning |
|---|---|---|
| `LINKIT_DATA_DIR` | your user data folder | Where everything is stored |
| `LINKIT_LOG_LEVEL` | `INFO` | Console log level |
| `LINKIT_PROVIDER` | `codex_cli` | `codex_cli`, `claude_cli` or `litellm` |
| `LINKIT_MODEL` | provider's own | Model name (required for `litellm`) |
| `LINKIT_API_KEY` | none | API key for `litellm` |
| `LINKIT_API_BASE` | none | Local OpenAI-compatible server |
| `LINKIT_LLM_CONCURRENCY` | `1` | Parallel AI calls, 1 to 3 |
| `LINKIT_LLM_TIMEOUT_S` | `300` | Seconds to wait for one AI call |
| `LINKIT_TAILOR_MAX_GROWTH` | `0.10` | Most a segment may grow, in characters |
| `LINKIT_TAILOR_MAX_WORD_CHANGE` | `0.15` | Most of the CV that may change, in words |
| `LINKIT_TAILOR_MIN_SSIM` | `0.85` | Layout similarity needed on each page |
| `LINKIT_EMBEDDING_MODEL` | multilingual MiniLM | Local ranking model |

A choice made in the wizard beats the environment. A command-line flag (`--provider`,
`--model`) beats the wizard.

The ranking model (about 220 MB) is downloaded once, the first time you rank jobs.
