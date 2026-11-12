---
title: "Command line reference for the linkit command"
description: "Every linkit command: serve, doctor, run a single stage, bench, apply-probe, tailor a CV from the terminal, install LibreOffice, import a profile."
---

# Command line

The command is `linkit`. Run `linkit --help`, or `linkit <command> --help`, for the built-in text.
This page lists every command and option.

```text
linkit [--version] [--help] <command>
```

| Command | What it does |
|---|---|
| (none) | Same as `linkit serve` |
| [`serve`](#linkit-serve) | Start the web page |
| [`doctor`](#linkit-doctor) | Check outside tools |
| [`install-libreoffice`](#linkit-install-libreoffice) | Install the minimal LibreOffice |
| [`ai-check`](#linkit-ai-check) | Test the AI provider |
| [`profile import`](#linkit-profile-import) | Load a profile from JSON |
| [`search import`](#linkit-search-import) | Load search settings from TOML |
| [`run <stage>`](#linkit-run) | Run one pipeline stage |
| [`status`](#linkit-status) | Job counts by state and tier |
| [`jobs`](#linkit-jobs) | List jobs |
| [`tailor`](#linkit-tailor) | Tailor your CV to a job text |
| [`discover-boards`](#linkit-discover-boards) | Find company job boards in Common Crawl |
| [`bench`](#linkit-bench) | Measure quality on built-in fake jobs |
| [`apply-probe`](#linkit-apply-probe) | Try real postings in Practice mode |

`linkit --version` prints the installed version.

A typical session without the web page:

```bash
linkit profile import profile.json
linkit search import search.toml
linkit run discover
linkit run enrich
linkit run rank
linkit run score
linkit jobs --tier mid
linkit run apply        # a dry run unless live applying is on
```

Settings that come from environment variables (`LINKIT_DATA_DIR` and the others) are listed on
the [Install](install.md#settings-you-can-change) page.

## `linkit serve`

Start the local web page on `127.0.0.1`.

| Option | Default | Meaning |
|---|---|---|
| `--port INTEGER` | `8765` | Local port |
| `--open` / `--no-open` | `--open` | Open a browser tab |

## `linkit doctor`

Check Python (3.11 or newer), LibreOffice, a Chromium browser (Chromium, Chrome, Edge or Brave), Codex CLI, Claude CLI and Tectonic.
Prints `ok`, `MISSING` or `optional` for each. Exits with code 1 if Python or LibreOffice
is missing. No options.

## `linkit install-libreoffice`

```text
linkit install-libreoffice SOURCE
```

`SOURCE` is the minimal LibreOffice zip or folder made by `scripts/bundle_libreoffice.py`. It is
installed into the data folder and used before any system LibreOffice. The command fails if the
source has no `program/soffice.exe`.

## `linkit ai-check`

Send a tiny test prompt to the AI provider.

| Option | Meaning |
|---|---|
| `--provider TEXT` | `codex_cli`, `claude_cli` or `litellm` |
| `--model TEXT` | Model name. Default is the provider's own. |

Without options it uses your wizard choice or the `LINKIT_*` environment. Exits with code 1
if the check fails.

## `linkit profile import`

```text
linkit profile import PATH
```

Load a JSON file with `full_name`, `email`, `phone`, `location`, `skills`, `cv_path` and
`locked_facts`. `full_name`, `email` and `cv_path` are required. The CV can be `.docx`, `.odt`,
`.pdf` or `.tex`. See [`profile.example.json`](profile.example.json).

## `linkit search import`

```text
linkit search import PATH
```

Load a `search.toml` file. See [`search.example.toml`](search.example.toml). It prints how many
queries, locations and companies it saved. An invalid file is refused with the reason.

## `linkit run`

Run one pipeline stage. Stages are independent and can be repeated. They use the saved search
settings, so import them or use the wizard first.

| Command | Stage | Options |
|---|---|---|
| `linkit run discover` | Fetch jobs from every source. Resumes an unfinished run. | `--new` starts a new run |
| `linkit run enrich` | Fetch missing job descriptions | none |
| `linkit run rank` | Hard filters and local ranking | none |
| `linkit run score` | AI scoring and tiers | `--provider`, `--model` |
| `linkit run apply` | Tailor and fill applications. A dry run unless live applying is on. | none |

`discover` also prints sources that were skipped and the errors it met.

## `linkit status`

Print the number of jobs in each state, and in each tier.

## `linkit jobs`

List jobs, best first.

| Option | Default | Meaning |
|---|---|---|
| `--tier TEXT` | all | `high`, `mid` or `low` |
| `--state TEXT` | all | A job state, for example `ranked` or `awaiting_review` |
| `--limit INTEGER` | `20` | Rows to show |

## `linkit tailor`

```text
linkit tailor JD [--title TEXT] [--company TEXT] [--out PATH] [--provider TEXT] [--model TEXT]
```

Tailor your saved CV to the job description in the text file `JD`. Prints the red-line patch list,
the layout check, and the path of the PDF.

| Option | Meaning |
|---|---|
| `--title TEXT` | Job title |
| `--company TEXT` | Company name |
| `--out PATH` | Output folder. Default is a new folder under `tailored/` in the data folder. |
| `--provider TEXT`, `--model TEXT` | Override the AI choice |

This is for checking what tailoring does. The web page and `linkit run apply` tailor
automatically.

## `linkit discover-boards`

```text
linkit discover-boards [--ats TEXT]... [--max-per-ats INTEGER]
```

Look up company job boards in Common Crawl's public index and store them, so the next
discovery crawls them too. Only Common Crawl is contacted; nothing about you is sent.

| Option | Default | Meaning |
|---|---|---|
| `--ats TEXT` | all | Only this applicant tracking system (repeat for more) |
| `--max-per-ats INTEGER` | `5000` | Boards to keep per system |

## `linkit bench`

```text
linkit bench [--jobs INTEGER] [--seed INTEGER] [--out PATH] [--apply INTEGER] [--provider TEXT] [--model TEXT]
```

Measure finding, duplicate removal, the scam and ghost checks, ranking and the CV tailoring
guard on a built-in fake job board, and write the numbers to `bench.json`. It touches none of
your data and no real site, and the AI is a scripted stand-in. The same seed gives the same
numbers.

| Option | Default | Meaning |
|---|---|---|
| `--jobs INTEGER` | `10000` | Fake jobs to generate (at least 10) |
| `--seed INTEGER` | `1` | Same seed, same jobs |
| `--out PATH` | `bench.json` | Where to write the numbers |
| `--apply INTEGER` | `0` | Also fill this many fake application forms in Practice mode (needs a browser) |
| `--provider TEXT`, `--model TEXT` | none | A real AI for the CV claim check only |

## `linkit apply-probe`

```text
linkit apply-probe [--per-source INTEGER] [--job INTEGER]... [--limit INTEGER] [--restore] [--scorecard PATH] [--provider TEXT] [--model TEXT]
```

Apply in Practice mode to real postings already in your job list, one per source by default,
then report where each one got to. Nothing is submitted, and the CV is sent as uploaded. The
[scorecard](scorecard.md) was made with it.

| Option | Default | Meaning |
|---|---|---|
| `--per-source INTEGER` | `1` | Jobs to try per source |
| `--job INTEGER` | none | Exact job ids (repeat for more) |
| `--limit INTEGER` | `60` | At most this many jobs in all |
| `--restore` | off | Only put back jobs an earlier test borrowed |
| `--scorecard PATH` | none | Also write a per-platform summary to this file |
| `--provider TEXT`, `--model TEXT` | none | Override the AI choice |
