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
| Scraping ethics | obey robots.txt, never defeat bot challenges (Wuzzuf search is disallowed and Cloudflare-protected, so the plugin reads its job sitemaps at Crawl-delay 10) |
| Embeddings | fastembed `paraphrase-multilingual-MiniLM-L12-v2` (220 MB, Arabic + English), chunked + mean-pooled; numpy cosine (sqlite-vec deferred) |
| AI scale | hard rules + free local rank first; only the top `ai_max_jobs` go to the AI, batched 10-20 per call |
| Tiers | score 8-10 high -> auto-apply; 5-7 mid -> user review; <5 or not AI-scored -> low (hidden, user may opt in) |
| Tailoring | just before applying, never for jobs that won't be applied to; reused if a job is requeued |
| ToS-risky features | LinkedIn Easy Apply, Indeed Apply, CapSolver: built later, off by default, ban-risk warning, low caps |
| Email verification | Gmail IMAP + app password first; Outlook OAuth later |
| Live applying | dry run by default (fill + screenshot, never submit). "Live applying" switch; then each submission waits for the user's click unless "Submit without asking" is also on |
| Demographic (EEO) questions | asked once in the setup wizard, each optional; if skipped and a form needs one, the job goes to the Action Center. The app never picks "decline" on its own |
| AI-drafted answers | used automatically, from CV + non-sensitive profile facts only, saved to the answer bank marked "ai" so the user can edit them |
| Cover letters | written whenever the form has a cover-letter field (text or file) |
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
- Opt-in (off by default, warning + low caps): LinkedIn Easy Apply, Indeed Apply, CapSolver.
- Action Center kinds: login_issue, two_factor (keep/restore the page where possible).

### Phase 6 — Generic agent ⬜
- Generic career-page extractor (JSON-LD -> CSS heuristics -> AI extraction) for any URL.
- Generic AI form agent: accessibility-tree snapshot -> field map JSON -> fill -> validate ->
  next page; the model decides, code executes; falls back to the Action Center.
- Naukrigulf and Forasna discovery (obeying robots.txt).

### Phase 7 — Later / release ⬜
- Local models (Ollama / LM Studio) setup in the wizard.
- LaTeX (Tectonic), ODT (LibreOffice round trip) and PDF (pdf2docx, user approves base) CVs.
- APScheduler for scheduled runs; desktop notifications.
- Outlook OAuth for verification emails.
- Reports over time, CSV/PDF export; Vault and Reports screens polished.
- Arabic/RTL UI, mobile layout check.
- macOS/Linux LibreOffice bundles; host bundles as release assets with a download step.
- MkDocs Material docs, GitHub repo + Actions, PyPI release.

## Known risks

- AI plan limits on Codex/Claude CLIs: batching, caching, clean pause/resume.
- CLI flag drift: adapters use flags checked against installed versions; tests use recorded outputs.
- DOCX fidelity: SSIM tolerance (0.85) needs tuning on real CVs.
- Anti-bot: LinkedIn rate-limits quickly; Lever uses hCaptcha and Greenhouse/Ashby reCAPTCHA
  (real Chrome with a persistent profile usually passes; visible challenges go to the
  Action Center). Never bypass challenges outside the opt-in CapSolver feature.
- ATS markup changes: handlers depend on container/label selectors; keep fixtures and
  re-check with the read-only inspection approach.
- ToS / account bans for LinkedIn/Indeed/CapSolver: opt-in only.
- Windows: Claude desktop is MSIX-packaged, so tools installed from the agent's shell into
  %APPDATA% are invisible to the user's terminals (see handoff.md).

## How work is verified

- `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`
  (e2e apply tests need Google Chrome; LibreOffice tests skip without it).
- Frontend: `cd frontend && npx ng build`.
- Live checks only read or dry-run: never submit a real application without the
  maintainer's explicit go-ahead.
