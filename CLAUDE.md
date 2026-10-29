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
- Python 3.11+ (dev 3.12), uv, hatchling. FastAPI + Uvicorn. Pydantic v2, pydantic-settings. Typer CLI.
- SQLite (WAL) via SQLAlchemy 2 typed `Mapped` models + Alembic; API schemas are separate
  Pydantic models (no SQLModel). Vectors: numpy cosine; sqlite-vec only if measured slow.
- Background work: asyncio worker pool inside the FastAPI process; `jobs.state` is the queue.
- APScheduler (SQLAlchemy job store), aiolimiter, tenacity, loguru (redaction filter), platformdirs.
- AI: LiteLLM (API keys, Ollama/LM Studio); subprocess adapters for `codex exec --json` and `claude -p --output-format json`.
- Scraping: httpx (async), python-jobspy, Playwright, selectolax, extruct, trafilatura, rapidfuzz, lingua-py. Embeddings: fastembed.
- CV: python-docx + lxml, pylatexenc/TexSoup + Tectonic, pdf2docx, LibreOffice headless
  (DOCX->PDF, ODT<->DOCX), PyMuPDF, pdfplumber, Pillow/scikit-image (layout diff).
- Apply: Playwright (real installed Chrome launched without automation flags, attached over CDP, persistent profile per site), imap-tools, vault via cryptography
  (AES-GCM) + argon2-cffi + keyring.
- Frontend: Angular + TypeScript + Tailwind, Chart.js, ngx-fast-diff; built into the wheel.
- Tooling: ruff, mypy, pre-commit, pytest (+ HTML fixtures), GitHub Actions, MkDocs Material.

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
- Every transition writes a `job_events` row (timestamp, state, message, artifact paths).
- Every stage is idempotent, resumable after crash or pause, and runnable alone (CLI + API).

## 5. Module logic
### 5.1 AI provider layer (`providers/`)
- One `LLMProvider` interface: `complete(prompt, schema) -> validated Pydantic object`.
  Providers: `codex_cli`, `claude_cli`, `litellm` (module `litellm_api`; local servers via
  `api_base`, wizard's Local model option). Pick with `LINKIT_PROVIDER`; test: `linkit ai-check`.
- CLI adapters (`codex_cli`, `claude_cli`): detect binary on PATH + version; verify sign-in with
  a tiny test prompt; run in an empty temp dir with the CLI's own tools disabled (check
  `--help` of the installed version for flags); prompt via stdin, parse JSON output; 1 call
  at a time by default; map usage-limit errors to a clean run pause. Setup notes that usage
  counts against the user's plan limits (vendor policy can change: keep swappable).
- All outputs are JSON validated against schemas; retry on invalid output (max 2).
- The model only decides; our code executes (never let it drive the browser).
  Cache responses in SQLite by prompt hash; track quota. CLI concurrency cap: 1–3. Prompts: `prompts/*.j2`.

### 5.2 Discovery (`sources/`)
- Plugin per source: `search(query) -> JobStub[]`, `fetch_details(stub) -> Job`. Plugins live in
  `sources/ats|aggregators|boards|companies` (auto-registry; helpers in `sources/common.py`, `parsing.py`,
  `tasks.py`). Aggregators/boards/companies/Telegram are opt-in.
- Priority: public ATS JSON APIs (Greenhouse, Lever, Ashby, Workday cxs, 100+ more) > python-jobspy (LinkedIn, Indeed, Glassdoor, ZipRecruiter,
  Google, Bayt) > aggregators and per-site plugins (Wuzzuf, Forasna) > generic extractor (JSON-LD -> CSS -> AI extraction).
- Also: Telegram channels (t.me/s preview), discovered boards (Common Crawl, `linkit discover-boards`), aggregator API keys from the vault.
- All browser automation runs real installed Chrome launched without automation flags (stealth-browser-mcp approach, maintainer 2026-10-26); never
  solve CAPTCHAs/challenges, automate login, use rotating proxies, TLS or fingerprint spoofing (exception 2026-10-29: headless gets a fitted screen +
  real Chrome UA/client hints). OK: what the site's own pages send (Referer, XHR header, CSRF key). robots.txt not enforced.
- ATS detector routes any pasted URL (or careers-page HTML) to the right plugin.
- LinkedIn hiring posts (`sources/linkedin_posts/`): opt-in, off by default, ban-risk warning, low caps. Dedicated `linkedin` Chrome profile; scraping
  headless by default (setting), search without filters + "Load more". Logged out or security check -> stop and notify. Never automate login, bypass
  challenges, comment, DM or react. ATS links -> that ATS; other posts -> batched AI extraction; no email/link -> dropped.
- Per-domain rate limits, page checkpoints, dedupe by normalized URL + hash(title, company, location) + rapidfuzz.

### 5.3 Matching (`matching/`)
1. Hard rules: titles include/exclude, location, remote mode, seniority, posted date,
   salary floor, company blacklist, one application per company (default on).
2. Local rank: 0.8 cosine(CV, JD) + 0.2 skills overlap; fastembed multilingual MiniLM-L12
   (Arabic + English, chunked). Free, no AI calls.
3. Trust check (offline, no AI): scam score (fees, off-platform contact, mule/crypto/ID requests,
   domain mismatch; EN+AR, evasion-proof) and ghost score (age, repeat sightings across runs,
   vague/evergreen text). Scam >= 65 -> filtered_out; ghost >= 50 -> tier low (or filtered out
   if the user opts in).
4. AI score only jobs that survive 1–3 (dropped ones become `low`), batched 10–20 short summaries
   per call: `{score 1-10, reasons, missing_skills, red_flags, legit, trust_flags}`; AI can raise, never clear.

### 5.4 Tailoring (`tailor/`)
- CV is split into numbered text segments; AI returns patches only: `[{segment_id, old_text, new_text, reason}]`. Never a full rewrite.
- Reject a patch if it: touches locked facts; adds unlisted skills/claims; grows a segment > ~10% chars; or
  total changed words exceed the configured cap (default 15%); `new_text` has Arabic script; the segment is mostly Arabic.
- DOCX: write new text into the first run of a span, empty the rest, keep run formatting. Cover body, tables,
  text boxes, headers/footers (lxml for what python-docx misses).
- LaTeX: edit text nodes only, compile with Tectonic. ODT: LibreOffice round-trip. PDF input: convert once via
  pdf2docx, user approves the base, then treat as DOCX.
- Output: LibreOffice -> PDF (submitted file). Verify: same page count, pixel/SSIM diff vs original within
  tolerance, pdfplumber text extract succeeds. On failure roll back patches.
- Store every tailored version + patch list per job (UI red-line diff). Debug: `linkit tailor jd.txt`. Numbers/dates/contacts are auto-locked.

### 5.5 Apply (`apply/`)
- Order: per-ATS handler -> generic AI form agent (accessibility-tree snapshot -> field map JSON -> fill -> validate -> next) -> Action Center.
  Handlers today: Greenhouse, Lever, Ashby; every other site (Workday, iCIMS, Taleo, ...) falls back to the generic agent.
- Headed Chrome by default, persistent profile per site, human pacing, per-site daily caps, 1–3 parallel
  browsers. Jobs closed on Greenhouse/Lever/Ashby are skipped before tailoring.
- Account gate: generate unique password (`secrets`, honoring site rules), save to vault BEFORE submitting
  signup, then verify via IMAP (code/link by regex, AI fallback). Dry run never touches sign-up; live mode
  creates accounts when needed; the application still waits for confirmation unless 'submit without asking'.
- Screening questions: answer bank (embedding match) -> AI draft from profile -> Action Center. Sensitive
  categories (section 2) never go to the AI. Sponsorship left on "Ask me" is answered per job from
  `authorized_countries` + the job country; unknown country -> Action Center.
- Missing setup parks the job with `needs_vault`, `vault_locked` or `needs_email`; it continues once done (`retry-code`).
- LinkedIn Easy Apply and Indeed Apply break those sites' ToS: off by default, explicit opt-in with a ban-risk
  warning, low daily caps. No CAPTCHA solving: CAPTCHAs park for the user.
- Email applications (`mailto:`, `apply/email_apply.py`): Gmail/Yahoo SMTP, vault app password; short cover
  email (greeting/signature in code, body from the model, CV/profile only) + tailored CV PDF. Dry run writes an
  .eml only; live follows "submit without asking" (else `confirm_email`). 15/day, never the same address twice.
- Cover letter only if the form has a field. All AI-written prose is English only, never Arabic (copying stays verbatim). Screenshot before submit and on confirmation; trace on failure.
- Success = confirmation page text and/or email, else failed with reason, never assumed. A sent email = applied
  (by email); the sent message is the proof.

### 5.6 Tiers (review)
Defaults, editable in settings: score 8+ = `high` -> auto-apply; 5–7 = `mid` -> user approval (review queue, bulk
approve/reject); <5 or dropped by prefilter = `low` -> hidden, but the user may opt in to auto-apply low too.

### 5.7 Action Center (UI: "Needs you", tabs Approve jobs = review, Finish applications)
Parked: unknown_question, confirm_submit, confirm_email, captcha, validation_error, login_issue,
two_factor. Reopen via "Open in app browser" (same Chrome profile), then Retry. Notify via
WebSocket + optional desktop notification. Open questions are grouped and answered once for many; sensitive
ones group only on exact wording. One-time "always" choices (agreements, notice period, relocation,
demographics) are saved to the profile.
### 5.8 Reports
Applied / failed / skipped / needs_user per platform and career page, per run and over time;
funnel (found -> ... -> applied); CSV/PDF export.
### 5.9 Setup values (`core/infer.py`, `core/presets.py`)
Derived by rules. AI gap-fill must be verbatim from the CV (checked). Nothing is written until the user confirms.

## 6. Data & security
- App data under platformdirs user data dir: db, CVs, tailored versions, screenshots, traces.
- Vault: AES-GCM, key from master passphrase via Argon2id, cached with keyring; export re-asks it.
  Created just in time (first account sign-up or Gmail added), not as a setup step. Crypto unchanged.
- IMAP: app passwords (Gmail first, Yahoo). Outlook needs an OAuth path (later).
- External tools: LibreOffice required (DOCX->PDF), Chrome for applying, Tectonic for LaTeX.
  `linkit doctor` checks them. End-user install: `uv tool install linkit-all`.
- LibreOffice: minimal portable bundle (Win 1.6 GB -> 439 MB) from `scripts/bundle_libreoffice.py` (removals kept only if renders stay identical);
  `linkit install-libreoffice <zip>` installs it to the data dir, ahead of any system install. Keep its MPL-2.0 license files.
- Profile, preferences, locked facts, answer bank stored in DB; JSON/YAML import/export.

## 7. UI screens
First run `/welcome` (CV, AI, check what we found, what jobs) · Home (next best action, funnel, schedule, tasks,
go-live) · Jobs (virtualized) · Needs you · Activity (Now = event stream + 3-second read-only screenshot view;
History = runs + reports) · Settings (Profile & CV, Jobs & places, Sources, Answers, Applying, Accounts & email,
AI, Advanced; everything autosaves).
UI words: Practice mode, Applying for real, Strong/Possible/Weak match, Needs you, Search. Code names unchanged.

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
  reports/ · cli.py  `linkit` (serve), `linkit doctor`, `linkit run <stage>`
frontend/     Angular 21 app (pages: welcome, home, jobs, needs-you, activity, settings/) -> src/linkit_all/static (Angular 22 needs Node >= 24.15)
tests/        unit, fixtures/<ats>/*.html, e2e (dry-run only) · docs/
```

## 9. Working rules for agents
- Small, focused changes; one module per task when possible. Don't refactor unrelated code.
  Type hints everywhere; ruff + mypy clean; tests for every new logic path.
- New source or ATS handler = plugin + fixture + tests. No live-site calls in CI; E2E apply tests are dry-run only, never submit real applications.
- Update this file when a decision in it changes (max 200 lines). Unsure? Ask; don't guess.

## 10. Build order
Phases 1-12 are built; blocked items: handoff.md.
1. Core: models, SQLite, state machine, providers (Claude/Codex CLI, API keys), DOCX tailoring.
2. Discovery + matching: ATS APIs, jobspy, Wuzzuf, Forasna, careers pages, dedupe, AI tiering.
3. UI v1: setup wizard, jobs, review queue, live run, report.
4. Apply v1: Greenhouse, Lever, Ashby (no accounts), answer bank, Action Center.
5. Apply v2: vault, IMAP, account gate built; Workday/iCIMS/Taleo/SuccessFactors blocked (need pages); LinkedIn/Indeed apply not built.
6. Generic careers extractor and AI form agent: built. Naukrigulf blocked.
7. Local models, LaTeX/ODT/PDF CVs, scheduler, reports, Arabic UI, docs: built. Pending: Outlook OAuth, macOS/Linux LO bundles, release.
8. freehire (MIT) ports: ATS feeds, aggregators, boards, companies, Telegram, discovery: built.
9. Debt (D1-D7) and 10. Trust filter: built.
11. LinkedIn hiring posts: built except the scraper (needs a captured page).
12. UX for V1 (ux-plan.md): built. UX7, the usability round with 5 people, is pending with the maintainer.

## 11. License
AGPL-3.0-or-later (code reused from ApplyPilot/AIHawk). Reused files keep original headers, listed in NOTICE.
