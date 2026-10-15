# CLAUDE.md — LinKit All: AI job search & auto-apply (open source)

Names: product "LinKit All" · Python package `linkit_all` · CLI command `linkit`.

Read this first in every session. Keep changes consistent with it. If a task conflicts
with a rule here, stop and ask the maintainer instead of working around it.

## 1. Goal
A local, open-source app that:
1. Fetches jobs (10,000+ per run) from any job board or company career page the user lists.
2. Ranks them against the user's CV and preferences.
3. Tailors the user's CV per job with minimal word-level edits, never touching layout or style.
4. Auto-applies to each job, including sites that require creating an account first.
5. Shows everything in a friendly local web UI: setup, live run view, review, results report.

Users bring their own AI: ChatGPT plan via Codex CLI, API keys, and later local models.

## 2. Hard constraints (never violate)
- NO fabricated CV content: never add skills, employers, titles, dates, degrees or metrics
  the user did not provide. Locked facts are immutable.
- NO AI-guessed answers for legal/sensitive questions: work authorization, visa,
  sponsorship, salary, EEO/demographics, disability, veteran status, criminal record,
  legal declarations. Answer only from the profile or queue for the user.
- All user data stays local. Only the chosen model provider receives CV/job text.
- No telemetry. No hard-coded secrets. Never log passwords, tokens or full CV text.
- Never click a final Submit in dry-run mode.

## 3. Tech stack (do not swap without approval)
- Python 3.11+ (dev pinned to 3.12), uv, hatchling. FastAPI + Uvicorn. Pydantic v2,
  pydantic-settings. Typer for the `linkit` CLI.
- SQLite (WAL) via SQLAlchemy 2 typed `Mapped` models + Alembic; API schemas are separate
  Pydantic models (no SQLModel). Vectors: numpy cosine; sqlite-vec only if measured slow.
- Background work: asyncio worker pool inside the FastAPI process; `jobs.state` is the queue.
- APScheduler (SQLAlchemy job store, scheduler phase only). aiolimiter. tenacity. loguru
  (with a redaction filter). platformdirs.
- AI: LiteLLM (API keys, Ollama/LM Studio); subprocess adapters for `codex exec --json` and `claude -p --output-format json`.
- Scraping: httpx (async), python-jobspy, Playwright, selectolax, extruct, trafilatura,
  rapidfuzz, lingua-py. Embeddings: fastembed (small bge model).
- CV: python-docx + lxml, pylatexenc/TexSoup + Tectonic, pdf2docx, LibreOffice headless
  (DOCX->PDF, ODT<->DOCX), PyMuPDF, pdfplumber, Pillow/scikit-image (layout diff).
- Apply: Playwright (installed Chrome, persistent context per site), imap-tools,
  cryptography (AES-GCM) + argon2-cffi + keyring for the vault.
- Frontend: Angular + TypeScript + Tailwind, Chart.js, ngx-fast-diff.
  Built frontend ships inside the Python wheel; end users never need Node for the UI.
- Tooling: ruff, mypy, pre-commit, pytest (+ saved HTML fixtures), GitHub Actions
  (Win/macOS/Linux), MkDocs Material.

## 4. Pipeline flow
Sources -> Discover -> Enrich -> Filter/Rank -> AI Score -> Tailor -> Review (optional)
-> Apply -> Report. Apply <-> Action Center (parked / resumed).

Job state machine (single source of truth, column `jobs.state`; tier in `jobs.tier`):
```
discovered -> enriched -> filtered_out | ranked -> scored
scored -> below_threshold (low) | awaiting_review (mid) | queued_apply (high/approved/low opt-in)
queued_apply -> tailored -> applying -> needs_user -> applied | failed | skipped
```
Tailoring happens just before applying, never for jobs that will not be applied to.
- Every transition writes a row to `job_events` (timestamp, state, message, artifact paths).
- Every stage is idempotent and resumable after crash or pause.
- Stages are independently runnable (CLI + API) for debugging.

## 5. Module logic

### 5.1 AI provider layer (`providers/`)
- One `LLMProvider` interface: `complete(prompt, schema) -> validated Pydantic object`.
- Adapters: `codex_cli`, `claude_cli`, `litellm_api` (also local OpenAI-compatible servers
  via `api_base`). Pick with `LINKIT_PROVIDER`; test with `linkit ai-check`.
- CLI adapters (`codex_cli`, `claude_cli`): detect binary on PATH + version; verify sign-in with
  a tiny test prompt; run in an empty temp dir with the CLI's own tools disabled (check
  `--help` of the installed version for flags); prompt via stdin, parse JSON output; 1 call
  at a time by default; map usage-limit errors to a clean run pause. Setup shows a note that
  usage counts against the user's own plan limits (vendor policy can change: keep swappable).
- All outputs are JSON validated against schemas; retry on invalid output (max 2).
- The model only decides; our code executes. Never let a model drive the browser directly.
- Cache responses in SQLite by prompt hash. Track quota; pause run cleanly on limit errors.
- CLI concurrency cap: 1–3. Prompts live in `prompts/*.j2`, not in code.

### 5.2 Discovery (`sources/`)
- Plugin per source with `search(query) -> JobStub[]` and `fetch_details(stub) -> Job`.
- Priority: public ATS JSON APIs (Greenhouse, Lever, Ashby, SmartRecruiters, Recruitee,
  Workable, Workday cxs endpoint) > python-jobspy (LinkedIn, Indeed, Glassdoor,
  ZipRecruiter, Google) > per-site scrapers (regional: Wuzzuf, Bayt, Naukrigulf, Forasna)
  > generic extractor (JSON-LD -> CSS heuristics -> AI extraction).
- ATS detector routes any pasted URL to the right plugin.
- Per-domain rate limits, checkpoints every page, dedupe by normalized URL +
  hash(title, company, location) + rapidfuzz near-duplicate check.

### 5.3 Matching (`matching/`)
1. Hard rules: titles include/exclude, location, remote mode, seniority, posted date,
   salary floor, company blacklist, one application per company (default on).
2. Local rank: fastembed cosine(CV, JD) + skills overlap. Free, no AI calls.
3. AI score only jobs that survive 1–2 (dropped ones become tier `low`), batched 10–20
   short job summaries per call: `{score 1-10, reasons, missing_skills, red_flags}` per job.

### 5.4 Tailoring (`tailor/`)
- CV is split into numbered text segments; AI returns patches only:
  `[{segment_id, old_text, new_text, reason}]`. Never a full rewrite.
- Reject a patch if it: touches locked facts; adds unlisted skills/claims; grows a segment
  > ~10% chars; or total changed words exceed the configured cap (default 15%).
- DOCX: write new text into the first run of a span, empty the rest, keep run formatting.
  Cover body, tables, text boxes, headers/footers (lxml for what python-docx misses).
- LaTeX: edit text nodes only, compile with Tectonic. ODT: LibreOffice round-trip.
  PDF input: convert once via pdf2docx, user approves the base, then treat as DOCX.
- Output: LibreOffice -> PDF (submitted file). Verify: same page count, pixel/SSIM diff vs
  original within tolerance, pdfplumber text extract succeeds. On failure roll back patches.
- Store every tailored version + patch list per job; UI shows a red-line diff.
- Until the wizard exists: `linkit profile import profile.json` (docs/profile.example.json),
  then `linkit tailor jd.txt` prints the red-line. Numbers/dates/contacts are auto-locked.

### 5.5 Apply (`apply/`)
- Order: per-ATS handler (Workday, Greenhouse, Lever, Ashby, iCIMS, Taleo, SmartRecruiters,
  SuccessFactors, LinkedIn Easy Apply, Indeed Apply) -> generic AI form agent
  (accessibility-tree snapshot -> field map JSON -> fill -> validate -> next) -> Action Center.
- Headed Chrome by default, persistent profile per site, randomized human pacing,
  per-site daily caps, 1–3 parallel browsers.
- Account gate: generate unique password (`secrets`, honoring site rules), save to vault
  BEFORE submitting signup, then verify via IMAP (code/link by regex, AI fallback).
- Screening questions: answer bank (embedding match) -> AI draft from profile ->
  Action Center. Sensitive categories (section 2) never go to the AI.
- LinkedIn Easy Apply, Indeed Apply and CapSolver break those sites' ToS: off by default,
  explicit opt-in with a ban-risk warning in UI + docs, low daily caps.
- Cover letter only when the form has a cover-letter field.
- Screenshot before submit and on confirmation; Playwright trace on failure.
- Success = confirmation page text and/or confirmation email. Otherwise state = failed
  with reason, never assumed applied.

### 5.6 Tiers (review)
Defaults, editable in settings: score 8+ = `high` -> auto-apply; 5–7 = `mid` -> user approval
(review queue, bulk approve/reject); <5 or dropped by prefilter = `low` -> hidden, but the
user may opt in to auto-apply low too.

### 5.7 Action Center
Queue of parked jobs: 2fa, unknown_question, validation_error, login_issue.
Keep or restore the page so the user acts in one sitting; job resumes afterward.
Notify via WebSocket + optional desktop notification.

### 5.8 Reports
Counts of applied / failed / skipped / needs_user per platform and per career page,
per run and over time; funnel (found -> filtered -> ranked -> scored -> applied); CSV/PDF export.

## 6. Data & security
- App data under platformdirs user data dir: db, CVs, tailored versions, screenshots, traces.
- Vault: AES-GCM, key from master passphrase via Argon2id, cached with keyring.
  Export requires re-entering the passphrase.
- IMAP: app passwords (Gmail first, Yahoo). Outlook needs an OAuth path (later).
- External tools: LibreOffice required (DOCX->PDF), Chrome for applying, Tectonic for LaTeX.
  `linkit doctor` checks them. Install for end users: `uv tool install linkit-all`.
- Profile, preferences, locked facts, answer bank stored in DB; JSON/YAML import/export.

## 7. UI screens
Setup wizard (profile, CV upload + preview, AI connection test, IMAP test, vault passphrase)
· Sources · Filters & matching · Jobs table (virtualized) · Review queue · Live run
(event stream + browser screencast) · Action Center · Vault · Reports.

## 8. Repository layout
```
src/linkit_all/
  api/        FastAPI routers, websockets
  core/       config, db models, state machine, events, scheduler
  providers/  LLM adapters + prompts/
  sources/    discovery plugins + ats_detector
  matching/   rules, embeddings, scoring
  tailor/     docx/, latex/, odt/, pdf_in/, render/, verify/
  apply/      handlers/<ats>.py, agent/, accounts/, vault/, email_verify/, answers/
  reports/
  cli.py      `linkit` (serve), `linkit doctor`, `linkit run <stage>`
frontend/     Angular app (built into src/linkit_all/static; created in build step 3)
tests/        unit, fixtures/<ats>/*.html, e2e (dry-run only)
docs/
```

## 9. Working rules for agents
- Small, focused changes; one module per task when possible. Don't refactor unrelated code.
- Type hints everywhere; ruff + mypy clean; tests for every new logic path.
- New source or ATS handler = plugin + fixture HTML + tests. No live-site calls in CI.
- E2E apply tests run in dry-run mode only. Never submit real applications in tests.
- Update this file when a decision in it changes (keep it under 200 lines).
- Unsure about scope, a constraint, or a dependency? Ask; don't guess.

## 10. Build order
1. Core: models, SQLite, state machine, provider layer (Claude CLI + Codex CLI + API keys), DOCX tailoring.
2. Discovery: Greenhouse/Lever/Ashby APIs, python-jobspy, regional boards (Wuzzuf, Bayt,
   Naukrigulf, Forasna; discovery only), dedupe, matching + batched AI tiering.
3. UI v1: setup wizard, jobs table, review queue, live run, basic report.
4. Apply v1: Greenhouse, Lever, Ashby (no accounts), answer bank, Action Center.
5. Apply v2: Workday, iCIMS, Taleo, SmartRecruiters, SuccessFactors with account creation,
   vault, Gmail IMAP verification. Opt-in: LinkedIn/Indeed apply, CapSolver.
6. Generic career-page extractor; generic AI form agent.
7. Later: local models, LaTeX/ODT/PDF input, scheduler, Outlook OAuth, docs, PyPI release.

## 11. License
AGPL-3.0-or-later (code is reused from ApplyPilot/AIHawk). Reused files keep their
original headers and are listed in NOTICE.
