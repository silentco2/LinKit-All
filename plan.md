# LinKit All — Master Plan

The full plan from first commit to public release. CLAUDE.md holds the rules every change
must follow; this file holds the roadmap and the decisions behind it. `handoff.md` describes
the exact current state and the next steps.

Status legend: ✅ done · 🟡 in progress · ⬜ not started

## Goal

A local, open-source app that finds jobs (10,000+ per run) on job boards and company career
pages, ranks them against the user's CV, tailors the CV per job with minimal word-level edits
(layout untouched), and applies automatically, including sites that need an account. A
friendly local web UI covers setup, live runs, review, the Action Center and reports. Users
bring their own AI: ChatGPT plan via Codex CLI, Claude plan via Claude Code CLI, API keys, and
later local models.

## Decisions (all confirmed with the maintainer)

| Topic | Decision |
|---|---|
| Backend | Python 3.11+ (dev pinned to 3.12.14), uv, hatchling, FastAPI + Uvicorn, Pydantic v2 |
| DB | SQLite (WAL), SQLAlchemy 2 typed models (no SQLModel), Alembic migrations run on startup |
| Background work | asyncio in the FastAPI process; `jobs.state` is the queue (no Huey) |
| Logging | loguru with a secret-redaction patcher |
| CLI | Typer; `linkit` with no command opens the UI |
| Frontend | Angular 21 (zoneless, signals) + Tailwind 4 + Chart.js + CDK virtual scroll, built into the wheel. Angular 22 needs Node >= 24.15 (dev machine has 24.12) |
| License | AGPL-3.0-or-later (code may be reused from ApplyPilot/AIHawk; NOTICE lists reused files) |
| Install | `uv tool install linkit-all`; `linkit doctor` checks external tools |
| PDF rendering | LibreOffice headless, shipped as a minimal portable bundle (1.6 GB -> 439 MB, 152 MB zip) via `scripts/bundle_libreoffice.py` + `linkit install-libreoffice` |
| First user | the maintainer (Egypt/MENA, DOCX CV, Gmail), then generalize |
| Search config | `search.toml` (stdlib tomllib) until the UI; now edited in the setup wizard; stored in the `search_config` table |
| Company boards | user's list + pasted URLs; the ATS detector maps URLs or careers-page HTML to Greenhouse/Lever/Ashby |
| Job sites | python-jobspy: LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter, and Bayt (jobspy supports Bayt natively) |
| Regional boards | Wuzzuf (own plugin via sitemaps), Bayt (jobspy); Naukrigulf, Forasna later |
| Scraping ethics | obey robots.txt (careers pages, site plugins; public ATS JSON APIs and jobspy sites exempt by maintainer decision 2026-10-16), never defeat bot challenges (Wuzzuf search is disallowed and Cloudflare-protected, so the plugin reads its job sitemaps at Crawl-delay 10) |
| Embeddings | fastembed `paraphrase-multilingual-MiniLM-L12-v2` (220 MB, Arabic + English), chunked + mean-pooled; numpy cosine (sqlite-vec deferred) |
| AI scale | hard rules + free local rank first; only the top `ai_max_jobs` go to the AI, batched 10-20 per call |
| Tiers | score 8-10 high -> auto-apply; 5-7 mid -> user review; <5 or not AI-scored -> low (hidden, user may opt in) |
| Tailoring | just before applying, never for jobs that won't be applied to; reused if a job is requeued |
| ToS-risky features | LinkedIn Easy Apply, Indeed Apply: built later, off by default, ban-risk warning, low caps |
| Email verification | Gmail IMAP + app password first; Outlook OAuth later |
| Live applying | dry run by default (fill + screenshot, never submit). "Live applying" switch; then each submission waits for the user's click unless "Submit without asking" is also on |
| Demographic (EEO) questions | asked once in the setup wizard, each optional; if skipped and a form needs one, the job goes to the Action Center. The app never picks "decline" on its own |
| AI-drafted answers | used automatically, from CV + non-sensitive profile facts only, saved to the answer bank marked "ai" so the user can edit them |
| Cover letters | written whenever the form has a cover-letter field (text or file) |
| Session scope (2026-10-16) | run Phases 4-7 continuously; stop only for blockers and outward-facing steps (GitHub repo, PyPI release, live submissions, real account creation) |
| Commits | one small commit on main per reviewed task |
| CAPTCHAs | CapSolver dropped (paid). Automated CAPTCHA solving is not built; CAPTCHAs park in the Action Center, the user solves them in the open headed browser, the job resumes |
| Answer bank UI | its own page (`/answers`), edits set `source = "user"` |
| Sensitive questions | never sent to the AI: work authorization, sponsorship, salary, demographics, criminal record, legal acknowledgements (arbitration, certify), privacy acknowledgements, recording consent (AI notetakers). Answered only from saved answers or the user's own answer-bank entries; optional consents (marketing) are never ticked |

## Pipeline and states

```
Sources -> Discover -> Enrich -> Filter/Rank -> AI Score -> (Review) -> Tailor -> Apply -> Report
                                                                         Apply <-> Action Center

discovered -> enriched -> filtered_out | ranked -> scored
scored -> below_threshold (low) | awaiting_review (mid) | queued_apply (high / approved / low opt-in)
queued_apply -> tailored -> applying -> needs_user -> applied | failed | skipped
needs_user -> queued_apply (resolved in the Action Center) | applying | failed
failed -> queued_apply (retry); any unfinished state -> skipped
```

Every transition writes a `job_events` row. Stages are idempotent and resumable: discovery
checkpoints every page, ranked jobs left unscored are scored next run, a usage limit pauses
the run.

## Phases

### Phase 0 — Init ✅
uv project, folder tree, Typer CLI with `doctor`, ruff/mypy/pytest, pre-commit, CI matrix
(Win/macOS/Linux x 3.11-3.13), AGPL license + NOTICE, CLAUDE.md decisions.

### Phase 1 — Core ✅
- Settings (`LINKIT_*` env), loguru redaction, SQLAlchemy models, Alembic, WAL, state machine.
- AI providers: `codex_cli`, `claude_cli` (tools disabled, empty temp dir), `litellm`
  (API keys + local OpenAI-compatible servers); JSON schema in the prompt, validation + 2
  retries, prompt-hash cache, usage limits -> `UsageLimitError`.
- DOCX tailoring: segmenter (body, tables, text boxes incl. mc:Fallback, headers/footers),
  run-preserving patch applier, patch rules (locked facts, auto-locked numbers/dates/contacts,
  unlisted terms, +10% growth, 15% word cap), LibreOffice render, verify (pages, SSIM,
  text), rollback.
- Minimal portable LibreOffice bundle.

### Phase 2 — Discovery + matching ✅
- Plugins: Greenhouse, Lever (global + EU), Ashby APIs; jobspy sites; Wuzzuf (sitemaps +
  JSON-LD); generic JSON-LD JobPosting parser.
- Rate-limited retrying HTTP client (LinkedIn 1 req/2 s, Wuzzuf 1 req/10 s), checkpoints,
  dedupe (URL, hash, fuzzy title per company; company legal-suffix normalization).
- Matching: hard rules, local rank, batched AI tiering, one job per company.

### Phase 3 — UI v1 ✅
- FastAPI API under `/api`, WebSocket event stream, one background run at a time,
  LocalOnly middleware (loopback Host, same-origin writes and WebSockets).
- Angular screens: setup wizard, jobs table (virtualized + detail drawer), review queue,
  live run, report.

### Phase 4 — Apply v1 (Greenhouse, Lever, Ashby; no accounts) 🟡
Done:
- Answer engine (`apply/answers.py`), answer bank + AI drafts + cover letters (`apply/assist.py`).
- Form extraction/fill (`apply/form.py`), handlers (`apply/handlers/`), runner
  (`apply/runner.py`) with dry-run guard, confirm-before-submit, evidence, traces, caps.
- Action Center tables and API (`/api/actions`, `/api/profile/answers`).
- `linkit run apply`; `apply` is a pipeline stage.
- Verified by dry runs on live Airbnb, Palantir and OpenAI forms; offline e2e on a saved
  Lever form.
Execution tasks (status here, details in handoff.md "Next steps"):
- ✅ T4.1 API: answer bank list/edit/delete; job detail `filled` + event screenshots; tests
- ✅ T4.2 Setup wizard: "Application answers" + "Applying" steps; `apply` in STAGES
- ✅ T4.3 Action Center page + nav badge + live/dry-run indicator in the shell
- ✅ T4.4 Live run apply label/summary; job drawer filled answers + screenshots
- ✅ T4.5 Answer bank page
- ✅ T4.6 Browser check on smoke data, CLAUDE.md §5.5-5.7, handoff.md refresh
Remaining:
- UI: setup wizard steps "Application answers" (ApplicationAnswers incl. optional EEO and
  the two acknowledgement switches) and "Applying" (ApplySection: live, submit without
  asking, caps, pauses, headless) with clear warnings.
- UI: Action Center screen (answer questions, confirm submission with screenshot + filled
  answers, retry, "I applied by hand", skip), nav badge with open count.
- UI: Apply stage in Live run (label, summary), live/dry-run indicator.
- Answer bank screen (view/edit/delete saved answers, AI vs user source).
- Tests for the new UI-facing flows as needed; update CLAUDE.md §5.5-5.7 notes.
- Maintainer runs a first supervised live application.

### Phase 5 — Apply v2 (accounts) ⬜
- Vault: AES-GCM, key from a master passphrase via Argon2id, cached with keyring; export
  requires the passphrase; Vault UI screen.
- Account creation: unique password via `secrets` honoring site rules, saved to the vault
  BEFORE submitting signup; login reuse.
- Gmail IMAP verification (code/link by regex, AI fallback) with app passwords; IMAP test in
  the wizard.
- Handlers: Workday (cxs endpoint for discovery + per-tenant accounts), iCIMS, Taleo,
  SmartRecruiters, SuccessFactors; discovery plugins for SmartRecruiters, Recruitee,
  Workable, Workday.
- Opt-in (off by default, warning + low caps): LinkedIn Easy Apply, Indeed Apply.
- Action Center kinds: login_issue, two_factor (keep/restore the page where possible).

Execution tasks:
- ✅ T5.0 runner: check handler/job_info before tailoring (today a job is tailored, then skipped)
- ✅ T5.1 Vault core (`apply/vault/`): AES-GCM per secret, Argon2id key, keyring cache, lock/unlock, export; table + migration
- ✅ T5.2 Vault API + wizard "Vault" step + Vault screen
- ✅ T5.3 IMAP (core; API/wizard test in T5.4b) verification (`apply/email_verify/`): Gmail app password from the vault, code/link regex, AI fallback prompt; API test + wizard step
- ✅ T5.4 Accounts (`apply/accounts/`): password generator per site rules, save-to-vault before signup, login reuse; handler signup/login hooks; login_issue / two_factor parking
- ✅ T5.4b Email API + wizard "Email" step
- ✅ T5.4c Runner uses the server's unlocked vault instance (today only a keyring-remembered unlock reaches the runner)
- ✅ T5.5a Discovery: SmartRecruiters + Recruitee sources (+ detector, fixtures, tests)
- ✅ T5.5b Discovery: Workable + Workday cxs sources
- ⛔ T5.6 SmartRecruiters apply handler: the oneclick-ui form sits behind DataDome (bot challenge) and is client-rendered; needs a maintainer-saved rendered form, else the Phase 6 generic agent covers it
- ⛔ T5.7 Workday / iCIMS / Taleo / SuccessFactors handlers: forms sit behind sign-up; need maintainer-saved pages or a supervised live session
- ⛔ T5.8 Opt-in LinkedIn Easy Apply / Indeed Apply: need the maintainer's logged-in pages; off by default, ban-risk warning, low caps
Decisions made by the orchestrator (override any): dry run never touches sign-up forms (outcome says an account would be created); live mode creates accounts automatically when a form needs one (the application itself still waits for confirmation unless "submit without asking"); one vault entry per (ats, tenant); verification email matched by sender domain + time window, plain profile email (no plus-addressing).

### Phase 6 — Generic agent ⬜
- Generic career-page extractor (JSON-LD -> CSS heuristics -> AI extraction) for any URL.
- Generic AI form agent: accessibility-tree snapshot -> field map JSON -> fill -> validate ->
  next page; the model decides, code executes; falls back to the Action Center.
- Naukrigulf and Forasna discovery (obeying robots.txt).

Execution tasks:
- ✅ T6.1 Generic careers source (`sources/careers.py`): robots.txt helper, JSON-LD -> link heuristics -> AI extraction
- ✅ T6.2a Generic form agent core (`apply/agent/`): control snapshot, AI field map, fill via answer engine, one-page step
- ✅ T6.2b Agent in the runner: fallback for jobs with no handler, multi-page loop, guarded submit, account gate
- ✅ T6.1b Batch the careers AI extraction (10 pages per call; skip AI when heuristics suffice)
- ✅ T6.3 Forasna discovery (sitemaps + JSON-LD)
- ⛔ T6.3b Naukrigulf: drops non-browser clients at the edge; needs maintainer-saved sitemap slice + job pages, never a disguised client
- ✅ T6.4 robots.txt parser: `*`/`$` wildcards, merged groups, Crawl-delay from every group (stdlib parser misses these)

### Phase 7 — Later / release ⬜
- Local models (Ollama / LM Studio) setup in the wizard.
- LaTeX (Tectonic), ODT (LibreOffice round trip) and PDF (pdf2docx, user approves base) CVs.
- APScheduler for scheduled runs; desktop notifications.
- Outlook OAuth for verification emails.
- Reports over time, CSV/PDF export; Vault and Reports screens polished.
- Arabic/RTL UI, mobile layout check.
- macOS/Linux LibreOffice bundles; host bundles as release assets with a download step.
- MkDocs Material docs, GitHub repo + Actions, PyPI release.

Execution tasks:
- ✅ T7.1 Reports: per platform/board/run, over time, funnel; CSV + PDF export
- ✅ T7.4a ODT (LibreOffice round trip) and PDF (pdf2docx + user approval) CV input
- ✅ T7.4b LaTeX CV (TexSoup/pylatexenc text nodes, Tectonic compile)
- ✅ T7.2 Scheduler (APScheduler, SQLAlchemy job store) + desktop notifications
- ✅ T7.3 Local models (Ollama / LM Studio) in the wizard's AI step
- ✅ T7.5a i18n runtime dictionary + RTL + shell + Setup (decision: no @angular/localize, one build ships in the wheel)
- ✅ T7.5b translate remaining pages + mobile check per page
- ✅ T7.6 MkDocs Material docs
- ✅ T7.7 Gap backend (from the docs audit vs CLAUDE.md): "Open in app browser" for parked jobs (keep/restore page, §5.7) + honest park messages; tailoring patches on job detail (red-line, §5.4); live apply screenshot for the Live run page (§7 screencast-lite)
- ✅ T7.10 Opt-in auto-apply for low-tier jobs (§5.6)
- ✅ T7.11 UI for T7.7/T7.10 (Action Center button, job drawer red-line, Live run screenshot, matching toggle), after T7.5b
- ⛔ Outlook OAuth (needs an Azure app registration), macOS/Linux LibreOffice bundles (need those OSes or CI), GitHub repo + PyPI release (outward-facing: maintainer's go-ahead)

## Known risks

- AI plan limits on Codex/Claude CLIs: batching, caching, clean pause/resume.
- CLI flag drift: adapters use flags checked against installed versions; tests use recorded outputs.
- DOCX fidelity: SSIM tolerance (0.85) needs tuning on real CVs.
- Anti-bot: LinkedIn rate-limits quickly; Lever uses hCaptcha and Greenhouse/Ashby reCAPTCHA
  (real Chrome with a persistent profile usually passes; visible challenges go to the
  Action Center). Never bypass challenges; they park in the Action Center.
- ATS markup changes: handlers depend on container/label selectors; keep fixtures and
  re-check with the read-only inspection approach.
- ToS / account bans for LinkedIn/Indeed: opt-in only.
- Windows: Claude desktop is MSIX-packaged, so tools installed from the agent's shell into
  %APPDATA% are invisible to the user's terminals (see handoff.md).

## How work is verified

- `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
  (e2e apply tests need Google Chrome; LibreOffice tests skip without it).
- Frontend: `cd frontend && npx ng build`.
- Live checks only read or dry-run: never submit a real application without the
  maintainer's explicit go-ahead.

### Phase 8 — Sources ported from freehire (MIT) 🟡
Decisions (maintainer, 2026-10-24): port every adapter that works with honest plain HTTP, in
batches; adapters that need freehire's bot-protection layer (tls-client fingerprints,
Scrapling challenge-solving browser, rotating proxies, spoofed Googlebot/app user agents,
ALTCHA proof-of-work) are NOT ported (CLAUDE.md §5.2). Company lists come from a Common
Crawl discovery step plus the user's own list. Aggregator API keys live in the vault with a
Setup "API keys" section. Telegram: t.me/s web-preview reader, freehire's 95 channels plus
user-added (Arabic hiring words in the prefilter). Logic is re-implemented in Python, no
code copied verbatim; NOTICE credits freehire (MIT). Survey: scratchpad freehire-survey.md.
- ⬜ F0a Source framework: auto-registry (no shared registry edits), per-module detector
  patterns, shared helpers (403/429 retry-with-backoff, paging), per-source test files
- ⬜ F0b Boards table + `linkit discover-boards` (Common Crawl CDX per ATS) + per-run rotation caps
- ⬜ F0c API keys in the vault + Setup section + `api_key()` helper for sources
- ⬜ F0d Workday: 2,000-cap facet split, 403/429 backoff, details only for unseen jobs
- ⬜ F0e Telegram reader, channel table + Setup, Arabic prefilter, link-out to ATS, batched AI extraction
- ⬜ F1.x ATS feed adapters (~117), batches of ~12
- ⬜ F2.x Aggregator APIs (~50), batches of ~10
- ⬜ F3 Job boards (honest ones) + RSS
- ⬜ F4.x The 52 single-company plugins (minus bypass ones), batches of ~12
