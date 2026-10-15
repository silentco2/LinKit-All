# Handoff — LinKit All

Written 2026-10-16 for the next agent or developer. Read in this order: `CLAUDE.md` (rules,
binding), `plan.md` (roadmap and every decision), then this file (current state and next
steps). Ask the maintainer before changing a decision in either file.

## TL;DR

- Phases 0–3 are done. Phase 4 (apply to Greenhouse/Lever/Ashby, no accounts) is done in
  the backend; **its UI is not built yet**. That UI is the next task (see "Next steps").
- 112 tests pass (`uv run pytest`), ruff and mypy are clean, every phase is committed.
- Nothing has ever been submitted for real. Apply runs in dry-run mode by default and has
  only been exercised as dry runs on live forms plus an offline e2e with a fake submit.
- The end state is in `plan.md`: Phases 5 (accounts, vault, IMAP, more ATSs), 6 (generic
  extractor and AI form agent) and 7 (local models, other CV formats, scheduler, release).

## Environment (maintainer's machine)

- Windows 11, project at `D:\LinKit All`, git repo with no remote yet (GitHub comes later).
- Python 3.12.14 (uv-managed) in `.venv`; `requires-python >= 3.11`.
- Node 24.12, so the frontend is **Angular 21** (Angular 22 needs Node >= 24.15). Upgrading
  later is `ng update` once Node is updated.
- Google Chrome installed (Playwright uses `channel="chrome"`, no browser download).
- Codex CLI and Claude CLI installed and logged in **in the maintainer's own terminal**.
- LibreOffice: the minimal bundle is installed at
  `%LOCALAPPDATA%\linkit-all\tools\libreoffice` (the real data dir). The zip is in
  `build/lo/` (gitignored), built by `scripts/bundle_libreoffice.py`.

### Gotchas that cost time

1. **The Claude desktop app is MSIX-packaged.** Anything the agent's shell installs or writes
   under `%APPDATA%` / `%LOCALAPPDATA%` is redirected to
   `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\...`. It works for the agent but
   is invisible to the maintainer's terminals (example: a uv Python install broke `.venv` for
   the user). Install interpreters or global tools, and run anything that must land in the real
   data dir, through the Terminal panel (`run_in_terminal`). Writes under `D:\` are fine.
2. **CLI AI providers from the agent's shell** may fail auth (refresh tokens). `linkit
   ai-check` works from the maintainer's terminal; prefer that for live AI checks.
3. **Preview pane launcher**: starting `uv run linkit serve` from `.claude/launch.json` exits
   silently. Start the server in a background shell instead, e.g.
   `LINKIT_DATA_DIR="D:\LinKit All\build\smoke\data" uv run linkit serve --no-open --port 8766`,
   and make `launch.json` attach with `"url": "http://127.0.0.1:8766"`.
   `.claude/launch.json` is gitignored.
4. Windows console is cp1256: set `PYTHONIOENCODING=utf-8` for scripts that print Arabic or
   symbols like ✱.
5. ruff format rewrites `\u2019`-style escapes to literal characters; smart-quote lines in
   `tailor/patches.py` carry `# noqa: RUF001` on purpose.

### Scratch data (all gitignored under `build/`)

- `build/smoke/data` — a working data dir with about 2,100 real jobs (Stripe, Airbnb,
  OpenAI, Palantir, Notion, plus Cairo jobs from LinkedIn, Indeed, Bayt and Wuzzuf), a test
  profile "Jane Doe" with a generated CV, a search config and the downloaded embedding model.
  Use it with `LINKIT_DATA_DIR`.
- `build/forms` — saved live application pages (Greenhouse embed for Airbnb, Lever for
  Palantir, Ashby for OpenAI) with field dumps.
- `build/dryrun` — the last dry run against those three live forms, with screenshots.
- Throwaway inspection scripts lived in the agent's scratchpad (read-only form inspector,
  live dry-run harness); recreate them from the patterns in `tests/e2e/test_apply_lever.py`.

## How to run

```bash
uv sync
uv run linkit doctor                      # Python, LibreOffice, Chrome, Codex, Claude, Tectonic
uv run linkit                             # UI at http://127.0.0.1:8765 (same as `linkit serve`)
uv run linkit profile import profile.json # docs/profile.example.json
uv run linkit search import search.toml   # docs/search.example.toml
uv run linkit run discover|enrich|rank|score|apply   # one stage; `discover --new` starts a new run
uv run linkit status ; uv run linkit jobs --tier mid
uv run linkit tailor jd.txt               # debug: red-line patches for one job description
uv run linkit ai-check --provider codex_cli
cd frontend && npm ci && npx ng build     # UI -> src/linkit_all/static/browser
```

UI hot reload: `LINKIT_DEV_ORIGINS='["http://localhost:4200"]' uv run linkit serve --no-open`,
then `npm start` in `frontend/` (proxy in `frontend/proxy.conf.json`).

Checks before every commit: `uv run ruff check . && uv run ruff format --check . && uv run
mypy && uv run pytest` (pre-commit runs ruff + mypy). Frontend: `npx ng build` must be warning-free.

## Architecture map

```
src/linkit_all/
  cli.py            Typer CLI; `linkit` alone -> serve
  pipeline.py       run_stage(stage) for discover/enrich/rank/score/apply, shared by CLI and UI;
                    ai_settings() = CLI flags > wizard choice > env; shared embedder
  core/
    config.py       Settings (LINKIT_* env): data_dir, provider, model, tailoring thresholds,
                    embedding model, dev_origins
    models.py       runs, jobs, job_events, llm_cache, profile (+answers JSON), locked_facts,
                    tailored_cvs, search_config, source_checkpoints, answer_bank, action_items
    state.py        ALLOWED transitions; transition() writes job_events
    search.py       SearchConfig: search, sources, filters, matching, apply, ai sections
    profile.py      profile fields, DOCX upload checks, JSON import
    runs.py, db.py, log.py (redaction), tools.py (find soffice/chrome; bundled LO first)
    migrations/     Alembic; runs automatically in init_db()
  providers/        LLMProvider.complete(prompt, schema); claude_cli, codex_cli, litellm_api;
                    prompts/*.j2 (json_output, json_retry, ping, tailor, score, answer, cover_letter)
  sources/          base (JobStub, Task, Source), http (rate limits + retries), text (html->text,
                    URL/company normalization, hash), store (Deduper), runner (discover, enrich),
                    ats_detector, greenhouse, lever, ashby, jobspy_sites, wuzzuf, jsonld
  matching/         rules (hard filters, seniority), rank (Embedder, rank_jobs), score (AI tiers)
  tailor/           docx/segments, patches (rules), render/libreoffice, verify/layout, pipeline
                    (tailor_docx, tailor_for, tailor_job; reuses an existing tailored CV)
  apply/
    answers.py      Question, ApplicationAnswers, sensitive_category(), sensitive/standard
                    answers, option pickers, resolve_static()
    assist.py       AnswerBank (embedding match), ai_drafts, write_cover_letter,
                    answer_questions() (full resolution)
    form.py         page script that tags question containers (data-lk) and controls
                    (data-lk-input); fill(); lost_values() refill check
    handlers/       base (Handler, JobInfo, confirmation/CAPTCHA/error checks), greenhouse,
                    lever, ashby; HANDLERS registry
    runner.py       Applier (persistent Chrome per ATS), pick_jobs (caps), apply(),
                    click_submit() guard, apply_jobs(); ApplyBlocked, DryRunViolation
  api/              app (factory, lifespan, SPA fallback, serve), routes (all /api endpoints),
                    runner (PipelineRunner, one run at a time), events (EventBus + log sink),
                    security (LocalOnly middleware)
  static/browser/   built Angular app (gitignored, shipped in the wheel via hatch artifacts)
frontend/src/app/   app.ts (shell, nav, badges), api.ts, live.ts (WebSocket), types.ts,
                    pages/{setup,jobs,job-detail,review,live,report}.ts (inline templates)
scripts/bundle_libreoffice.py   builds the minimal LibreOffice bundle (Windows)
tests/unit, tests/e2e (apply flow on a saved Lever form), tests/fixtures/<ats>/
```

## Safety invariants (never break these)

- **No fabricated CV content**: tailoring patches are rejected if they touch locked facts,
  change numbers/dates/contacts, add terms absent from the CV and skill list, grow a segment
  by more than 10%, or exceed the 15% word cap. Layout check, or roll back.
- **Sensitive questions never reach the AI** (`apply/answers.py::_SENSITIVE`): they're
  answered only from `ApplicationAnswers` or the user's own answer-bank entries
  (`source == "user"`, near-identical wording, 0.97 similarity), otherwise parked. Optional
  acknowledgements and consents are never ticked. Add new categories there, with tests.
- **Dry run never submits**: the runner returns before the submit step, and
  `click_submit()` raises `DryRunViolation`. Keep both. Live mode also waits for the user's
  confirmation unless "submit without asking" is on.
- **Applied only on proof**: a job becomes `applied` only when the ATS confirmation page
  text is seen (or the user says "applied by hand"). Otherwise: Action Center or `failed`
  with a reason. Screenshots before submit and after; a Playwright trace on failure.
- **Local only**: the server binds to 127.0.0.1; `LocalOnly` rejects foreign Host headers and
  cross-origin writes and WebSockets. Screenshot endpoints serve files only from the data dir.
- **Privacy**: never log passwords, tokens or CV text (loguru patcher redacts secrets; log ids
  and counts). No telemetry. Only the chosen AI provider sees CV and job text.
- **Scraping**: obey robots.txt, never defeat bot challenges, keep per-host rate limits.
- **Tests**: no live-site calls in CI; e2e apply tests intercept every request. Never submit
  a real application without the maintainer's explicit go-ahead.

## What's built (by phase)

| Phase | State | Notes |
|---|---|---|
| 0 Init | ✅ | CI matrix in `.github/workflows/ci.yml` (Python + frontend build) |
| 1 Core | ✅ | providers verified live with Codex and Claude from the maintainer's terminal |
| 2 Discovery + matching | ✅ | live: 5 company boards -> 2,075 jobs in 12 s; Cairo searches on LinkedIn/Indeed/Bayt; Wuzzuf via sitemaps |
| 3 UI v1 | ✅ | all five screens checked in the browser with real data; a run started from the UI streamed live |
| 4 Apply v1 | 🟡 | backend + API done and tested; UI missing |
| 5–7 | ⬜ | see `plan.md` |

## Next steps (finish Phase 4)

### 1. Setup wizard: two new steps (`frontend/src/app/pages/setup.ts`)

Insert between "Filters" and "Finish":

**"Application answers"**: `GET/PUT /api/profile/answers` (body = `ApplicationAnswers` in
`apply/answers.py`; PUT returns 409 until the profile is saved).
- Basics: first/last name (optional overrides), city, country, current company/title,
  LinkedIn/GitHub/portfolio, years of experience, notice period, "how did you hear" default,
  willing to relocate (yes/no/ask me).
- Work and visa (sensitive): countries you can work in (one per line), need sponsorship
  (yes/no/ask me), salary expectation + currency.
- Voluntary demographics, each optional, with "Ask me when a form needs it" as the empty
  default: `eeo_gender` (male, female, non_binary, decline), `eeo_race` (asian, black,
  hispanic, white, middle_eastern, native, pacific, two_or_more, decline), `eeo_hispanic`
  (yes, no, decline), `eeo_veteran` (not_veteran, veteran, decline), `eeo_disability`
  (no, yes, decline). Label "decline" as "Prefer not to say".
- Acknowledgements: `acknowledge_privacy` ("Accept required privacy notices and
  data-processing consents for me") and `acknowledge_legal` ("Accept required arbitration
  agreements and 'I certify my answers are true' statements for me"). Tri-state; empty means
  the Action Center asks each time. Explain both plainly.

**"Applying"**: the `apply` section of `PUT /api/search` (`ApplySection` in
`core/search.py`): `live` (big warning: real applications), `submit_without_asking`
(disabled unless live; second warning), `max_per_run`, `daily_cap_per_site`, `headless`,
`min_pause_s`/`max_pause_s`. Show the current mode in the shell (`/api/status` has
`apply_live`).

### 2. Action Center screen (new `pages/actions.ts`, route `actions`, nav badge)

- `GET /api/actions?status=open` -> items: `id, kind, message, questions[], answers{}
  (filled summary: label -> {value, source}), screenshots (count), job{id, title, company,
  location, score, url, apply_url}`.
- Screenshot: `<img src="/api/actions/{id}/screenshot/{n}">`.
- `POST /api/actions/{id}` with `{"decision": ..., "answers": {label: value}}`:
  - `answer` (kind `unknown_question`): render each question by `kind` (select/radio/
    combobox/yesno -> choices from `options`; multi -> checkboxes; checkbox -> yes/no; text ->
    input; textarea -> textarea), show `reason` and a "sensitive" note. Required ones are
    enforced (422 lists the first missing). Answers go to the answer bank as the user's, and
    the job is requeued.
  - `confirm` (kind `confirm_submit`): show the screenshot and the filled answers table with
    source badges (profile, sensitive, bank, ai, file), then "Submit application" and "Skip".
  - `retry`, `applied_by_hand` (shows an "Open application page" link to `apply_url`),
    `skip` for `captcha` / `validation_error`.
- `/api/status.actions_open` drives the nav badge. Refresh on `Live.changed()`.

### 3. Live run and Jobs

- Add `apply` to `STAGES` in `frontend/src/app/types.ts` and a label ("Apply" plus
  "(dry run)" / "(live)") in `pages/live.ts`; summary from the result counts
  `dry_run, applied, needs_user, failed, skipped`.
- Job detail drawer: show the dry-run `filled` answers (`job.data.filled`, via a small API
  addition to `/api/jobs/{id}`) and links to screenshots.

### 4. Answer bank screen (small)

New endpoints: list, edit and delete `answer_bank` rows (question, answer, source,
sensitive, uses). Editing an AI answer should set `source = "user"`.

### 5. Wrap up Phase 4

- Tests for new endpoints; `npx ng build` clean; browser check of each screen against
  `build/smoke/data` (run a dry-run apply from the UI on smoke jobs that have Greenhouse,
  Lever or Ashby `ats`).
- Update CLAUDE.md §5.5–5.7 if behavior changed (it is at its 200-line cap; tighten
  something else rather than grow it).
- With the maintainer: a first supervised live application (Live on, confirm each).

## Knowledge from the live forms (keep handlers aligned)

- **Greenhouse**: companies often redirect the hosted board to their own site; use the embed
  form `https://boards.greenhouse.io/embed/job_app?for={board}&token={id}`. The questions API
  `https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{id}?questions=true` gives labels,
  required flags and dropdown values keyed by field name (= control id). Dropdowns are
  react-select comboboxes (type, then pick a `role=option`). Phone is an intl-tel-input
  widget: containers `.phone-input__country` / `.phone-input__phone`; ignore
  `.iti__search-input` and `[class*=requiredInput]`. File labels are in `.upload-label`. The
  form resets early-filled inputs while hydrating (networkidle wait + refill check).
- **Lever**: `li.application-question` / `.application-label` (✱ marks required). Custom
  questions are `cards[...]` radios, checkboxes and selects. A university select can have
  thousands of options (the prompt sends "long list; answer with the exact name"). Submit is
  `#btn-submit` (type=button), which runs hCaptcha, then a hidden submit button. Never click
  the hidden one.
- **Ashby**: `.ashby-application-form-field-entry` plus fieldsets
  `.ashby-application-form-input-radio-group` / `-checkbox-group`; title
  `.ashby-application-form-question-title`; required is only a CSS class (`_required_...`);
  Yes/No questions are typeless `<button aria-pressed>` toggles with a hidden checkbox;
  checkbox inputs in groups are named after the option text; the first file input on the page
  is the "autofill from resume" widget (outside the containers, so ignored). Submit is
  `button.ashby-application-form-submit-button`. Pages carry reCAPTCHA.
- Real forms seen: Airbnb asks work authorization/sponsorship with long "Yes, I am..."
  options; Palantir asks AI-notetaker recording consent and UK security clearance; OpenAI
  asks US work authorization, an arbitration agreement and a "certify" statement.

## Known issues and debt

- CLAUDE.md is at its 200-line cap.
- `SearchConfig` now also holds `ai` and `apply` settings (it's really "preferences"); renaming
  would touch the API, UI and saved data, so it was left.
- Dedupe collapses same-title openings at the same company and location (fine while one job
  per company is the default).
- Wuzzuf fetches only slugs containing every word of a query (each fetch costs 10 s).
- A combobox with no fixed options (city, country) picks the first suggestion after typing.
- Live submission is untested against real sites (CAPTCHA behavior unknown); the first live
  run must be supervised.
- When `ApplyBlocked` fires (AI limit, LibreOffice missing) the rest of that run's jobs wait
  for the next run.
- Starlette's TestClient warns about httpx (`httpx2`); harmless.
- `linkit run apply` exists, but `/api/runs` stage pickers in the UI don't offer `apply` yet.

## Conventions

- Small focused commits; message body explains what and why; end with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Keep the code lazy and boring: reuse what exists, stdlib first, no speculative
  abstractions; mark deliberate shortcuts with a `ponytail:` comment naming the ceiling.
- Type hints everywhere (mypy strict); a test for every new logic path; new source or
  handler = plugin + fixture + tests; fixtures are trimmed copies of real responses.
- Prompts live in `providers/prompts/*.j2`, never inline; every AI output is validated
  against a Pydantic schema.

## Commit history

```
607fadf Phase 4c (API): application answers and Action Center endpoints
0b50535 Phase 4b: apply runner, Greenhouse/Lever/Ashby handlers, dry-run guard
e674216 Phase 4a: answer engine, answer bank, Action Center tables
e7fffb3 Phase 3 UI: Angular app with setup wizard, jobs, review, live run, report
fa8c8d4 Phase 3 API: FastAPI routes, pipeline runner, live events, `linkit serve`
2ee7f4f Phase 2: matching - hard rules, local ranking, AI tiering
468ee41 Phase 2: Wuzzuf source via sitemaps + generic JSON-LD JobPosting parser
15130db Phase 2: LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter, Bayt via jobspy
00558a4 Phase 2: discovery core + Greenhouse, Lever, Ashby sources
39fdc06 Minimal portable LibreOffice bundle for DOCX -> PDF
76beda7 Phase 1: DOCX tailoring (segments, patch rules, render, verify)
2aad096 Phase 1 core: settings, DB, state machine, LLM providers
36b8190 Initialize LinKit All project skeleton
```
(plus the commit that adds this file, `plan.md` and `linkit run apply`)
