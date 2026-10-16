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

Check Python (3.11 or newer), LibreOffice, Google Chrome, Codex CLI, Claude CLI and Tectonic.
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
