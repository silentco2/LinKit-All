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
- NO fabricated CV content: never add employers, titles, dates, degrees or metrics
  the user did not provide. Locked facts are immutable.
- NO AI-guessed answers for legal/sensitive questions: work authorization, visa,
  sponsorship, salary, EEO/demographics, disability, veteran status, criminal record,
  legal declarations. Answer only from the profile or queue for the user.
- All user data stays local. Only the chosen model provider receives CV/job text. Suggestions (places, titles, FX rates) come from bundled offline datasets; the only refresh, FX rates, sends no personal data.
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
- Apply: Playwright (an installed Chromium browser — Chrome, else Edge, Brave or Chromium; core/tools.py browser_path() launched without automation flags, attached over CDP, persistent profile per site), imap-tools, msal (Outlook sign-in), vault via cryptography
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
  Google, Bayt) > aggregators and per-site plugins (Wuzzuf, Forasna) > generic extractor (JSON-LD -> heading + page text; JS pages: AI picks a recipe once per site).
- Also: Telegram channels (t.me/s preview; post rules as for LinkedIn posts), discovered boards (Common Crawl, `linkit discover-boards`), aggregator API keys from the vault.
- All browser automation runs launched without automation flags (stealth-browser-mcp approach, maintainer); never
  solve CAPTCHAs/challenges, use rotating proxies, TLS or fingerprint spoofing (exception: headless gets a fitted screen +
  the browser's own real UA/client hints). OK: what the site's own pages send (Referer, XHR header, CSRF key). robots.txt not enforced.
- ATS detector routes any pasted URL (or careers-page HTML) to the right plugin.
- LinkedIn hiring posts (`sources/linkedin_posts/`): opt-in, off by default (ToS risk noted, no acknowledgement checkbox), no LinkedIn account (maintainer 2026-10-31); a row in the Sources list, keywords = the job titles (maintainer 2026-11-05). Google
  `site:linkedin.com/posts` in the app browser on a `google` profile (≤5 keywords × ≤5 pages, paced); a Google check -> stop the source, flag it, a Needs you
  card opens it in the app browser. Post text = public page JSON-LD only (never comments). ATS links -> that ATS; else by script, no AI (`sources/posts.py`, maintainer 2026-11-08): email -> mailto job, other link -> careers scraper, neither -> dropped.
- Per-domain rate limits, page checkpoints, dedupe by normalized URL + hash(title, company, location) + rapidfuzz.

### 5.3 Matching (`matching/`)
1. Hard rules: titles include/exclude, location (if not remote), remote mode, seniority, posted date,
   salary floor, company blacklist, one application per company (default on).
2. Local rank: 0.8 cosine(CV, JD) + 0.2 skills overlap; fastembed multilingual MiniLM-L12
   (Arabic + English, chunked). Free, no AI calls.
3. Trust check (offline, no AI): scam score (fees, off-platform contact, mule/crypto/ID requests,
   domain mismatch; EN+AR, evasion-proof) and ghost score (age, repeat sightings across runs,
   vague/evergreen text). Scam >= 65 -> filtered_out; ghost >= 50 -> tier low (or filtered out
   if the user opts in). Trash (`matching/trash.py`, maintainer): applied, reported, blacklisted-company and off-title jobs never reach a list; rows stay for dedupe.
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
  tolerance, pdfplumber text extract succeeds. On failure roll back patches. Tailoring is optional (`apply.tailor_cv`: None undecided, True tailor, False send the CV as uploaded): declined, or no LibreOffice in practice mode -> the original file, no AI call, event `tailor_skipped`; real applications without it wait (`needs_libreoffice`/`needs_tectonic`, run start answers 409).
- Store every tailored version + patch list per job (UI red-line diff). Debug: `linkit tailor jd.txt`. Numbers/dates/contacts are auto-locked.

### 5.5 Apply (`apply/`)
- Order: per-ATS handler -> generic AI form agent (accessibility-tree snapshot -> field map JSON -> fill -> validate -> next) -> Action Center.
  Handlers today: Greenhouse, Lever, Ashby; every other site (Workday, iCIMS, Taleo, ...) falls back to the generic agent.
  On a job ad (board listing) the agent presses Apply (<= 3 hops) and hands Greenhouse/Lever/Ashby links to their handler.
- Headedless browser (apply.headless), persistent profile per site, human pacing, per-site daily caps, 1–3 parallel
  browsers. Jobs closed on Greenhouse/Lever/Ashby are skipped before tailoring.
- Account gate: generate unique password (`secrets`, honoring site rules), save to vault BEFORE submitting
  signup, then verify via IMAP (code/link by regex, AI fallback). Dry run never touches sign-up; live mode
  creates accounts when needed; the application still waits for confirmation unless 'submit without asking'. Sign in with Google (`apply/google_signin.py`, `apply.google_signin`, opt-in, live only, maintainer): the user signs in to Google by hand once on the `generic` profile; the agent presses the site's button, the account and Continue, never typing Google's password or solving its checks (those park, `google_needed`).
  Sites without a handler (job boards, maintainer): same gate in the agent, vault account `web:<host>`, sign-up via field map + answer engine.
- Screening questions: answer bank (embedding match; general/per-role/per-company by wording, `assist.scope_of`) -> AI draft from profile (saved) -> Action Center. LinkIt Fill reads labels itself (no form-map AI); what the user types or corrects there joins the bank (never sensitive, secrets, ticks, dates). Sensitive
  categories (section 2) never go to the AI; military status, nationality, date of birth and marital status
  come from the profile only (an age question is always asked). Sponsorship/work authorization left on "Ask me":
  job country in `authorized_countries` -> no sponsorship/authorized, in `visa_countries` -> sponsorship needed/not authorized, else Action Center.
- Missing setup parks the job with `needs_vault`, `vault_locked` or `needs_email`; it continues once done (`retry-code`).
- Ban-risk sites (`apply.assisted_hosts`: LinkedIn, Indeed, Glassdoor; maintainer 2026-11-07) are never driven and get no
  account: the job parks `apply_in_browser`. The user opens it in their own browser, where the LinkIt Fill extension
  (`src/linkit_all/extension/`, MV3, pairing token, `api/assist.py`) fills each step, or any page by right-click "Fill with LinkIt" (AI for optional fields too; page -> job by site job id, address, or title + company, never a guess; the job follows its Apply into the employer's tab; LinkedIn's public page shows offsite vs Easy Apply, not where); the user presses Next/Submit.
  Dead ends park `apply_by_hand` (link, CV, answers so far). No CAPTCHA solving: CAPTCHAs park for the user.
- Email applications (`mailto:`, `apply/email_apply.py`): Gmail/Yahoo SMTP or Outlook Graph; short cover
  email (greeting/signature in code, body from the model, CV/profile only), subject = job title, the CV as uploaded (never tailored). Dry run writes an
  .eml only; live follows "submit without asking" (else `confirm_email`). 15/day, never the same address twice. LinkIt mail: hover an address in a page, the extension offers to email it; the press is the go-ahead, sent at once (live only, `POST /api/assist/email`).
- Names (`core/names.py`): split on spaces; other script from the bundled arabnamer list, no AI. Cover letter only if the form has a field. All AI-written prose is English only, never Arabic (copying stays verbatim). Screenshot before submit and on confirmation; trace on failure.
- Success = confirmation page text and/or email, else failed with reason, never assumed. A sent email = applied
  (by email); the sent message is the proof.

### 5.6 Tiers (review)
Defaults, editable in settings: score 8+ = `high` -> auto-apply; 5–7 = `mid` -> user approval (review queue, bulk
approve/reject); <5 or dropped by prefilter = `low` -> hidden, but the user may opt in to auto-apply low too.

### 5.7 Action Center (UI: "Needs you", tabs Approve jobs = review, Finish applications)
Parked: unknown_question, confirm_submit, confirm_email, captcha, validation_error, login_issue,
two_factor, apply_by_hand, apply_in_browser ("Open in my browser", "I applied"). Reopen via "Open in app browser" (same browser profile), then Retry. Notify via
WebSocket + optional desktop notification. Open questions are grouped and answered once for many; sensitive
ones group only on exact wording. One-time "always" choices (agreements, notice period, relocation,
demographics) are saved to the profile.
### 5.8 Reports
Applied / failed / skipped / needs_user per platform and career page, per run and over time;
funnel (found -> ... -> applied); CSV/PDF export.
### 5.9 Setup values (`core/infer.py`, `core/presets.py`)
Derived by rules. AI gap-fill must be verbatim from the CV (checked). On CV upload/approve the CV fills EMPTY non-sensitive profile fields only (never overwrites, never sensitive; `authorized_countries` stays a suggestion) and its employers, titles, degrees and schools join the locked facts automatically.

## 6. Data & security
- App data under platformdirs user data dir: db, CVs, tailored versions, screenshots, traces.
- Vault: AES-GCM, key from master passphrase via Argon2id, cached with keyring; export re-asks it.
  Created just in time (first account sign-up or Gmail added), not as a setup step. Crypto unchanged.
- IMAP/SMTP: app passwords (Gmail, Yahoo). Outlook/Hotmail: msal loopback sign-in (our Azure app id in config; `LINKIT_MS_CLIENT_ID` overrides), token cache in vault, mail via Microsoft Graph (IMAP XOAUTH2 fails server-side for personal accounts).
- External tools: LibreOffice required (DOCX->PDF), Chromium for applying (not needed with Chrome, Edge or Brave), Tectonic for LaTeX.
  `linkit doctor` checks them. End-user install: `uv tool install linkit-all`.
- LibreOffice: minimal portable bundle (Win 1.6 GB -> 439 MB) from `scripts/bundle_libreoffice.py` (removals kept only if renders stay identical);
  `linkit install-libreoffice <zip>` installs it to the data dir, ahead of any system install. Keep its MPL-2.0 license files. Optional in-app install (`POST /api/tools/libreoffice/install`, Windows x64 only unless env URL/hash are set): downloads `lo_bundle_url` (GitHub release `libreoffice-26.2.6-win-x64` of silentco2/LinKit-All, 145 MB), pinned `lo_bundle_sha256` checked before unpacking, never without a hash; the user may refuse and apply with the original CV.
- Profile, preferences, locked facts, answer bank stored in DB; JSON/YAML import/export.

## 7. UI screens
First run `/welcome` (CV, AI, check what we found, what jobs) · Home (next best action, funnel, go-live, run view = step cards (pause stops; play resumes, or on the next step counts the stopped one as done; Find new jobs discards it) +
event log + 3-second read-only screenshot view, report charts + folded tables, schedule; no Activity page, maintainer
2026-11-05) · Jobs (virtualized) · Needs you · Settings (Profile & CV, Jobs & places, Sources, Answers, Applying, Accounts & email,
AI, Advanced; everything autosaves).
UI words: Practice mode, Applying for real, Strong/Possible/Weak match, Needs you, Search. Code names unchanged.
Look (maintainer 2026-11-08): the application desk. Paper sheets on a desk, folder tabs for counts and trays, a rubber stamp for outcomes only. Tokens in `frontend/src/styles.css` (Tailwind slate/brand scales remapped there); IBM Plex Sans + Arabic bundled, never web fonts.

## 8. Repository layout
```
src/linkit_all/
  api/        FastAPI routers, websockets
  core/       config, db models, state machine, events, scheduler
  providers/  LLM adapters + prompts/
  sources/    discovery plugins + ats_detector
  matching/   rules, embeddings, scoring
  tailor/     docx/, latex/, odt/, pdf_in/, render/, verify/
  apply/      handlers/<ats>.py, agent/, accounts/, vault/, email_verify/, answers/, probe.py
  extension/  LinkIt Fill browser extension (MV3, plain JS; snapshot.js mirrors apply/agent/snapshot.js)
  reports/ · cli.py  `linkit` (serve), `linkit doctor`, `linkit run <stage>`, `linkit apply-probe`
frontend/     Angular 21 app (pages: welcome, home, jobs, needs-you, settings/) -> src/linkit_all/static (Angular 22 needs Node >= 24.15)
tests/        unit, fixtures/<ats>/*.html, e2e (dry-run only) · docs/
```

## 9. Working rules for agents
- Small, focused changes; one module per task when possible. Don't refactor unrelated code.
  Type hints everywhere; ruff + mypy clean; tests for every new logic path.
- New source or ATS handler = plugin + fixture + tests. No live-site calls in CI; E2E apply tests are dry-run only, never submit real applications.
- Ask before updating this file when a decision in it changes (max 200 lines). Unsure? Ask; don't guess.

## 10. Build order
Phases 1-13 are built; blocked items: handoff.md. 1 core, models, providers, DOCX tailoring · 2 discovery + matching
· 3 UI v1 · 4 apply v1 (Greenhouse, Lever, Ashby, answer bank, Action Center) · 5 vault, IMAP, account gate
(Workday/iCIMS/Taleo/SuccessFactors blocked: need pages) · 6 careers extractor, AI form agent (Naukrigulf blocked)
· 7 local models, LaTeX/ODT/PDF CVs, scheduler, reports, Arabic UI, Outlook OAuth (pending: macOS/Linux LO bundles,
release) · 8 freehire ports · 9 debt · 10 trust filter · 11 LinkedIn hiring posts · 12 UX for V1 (UX7 usability round pending) · 13 autonomous apply: Apply-button hops, board accounts, assisted sites + LinkIt Fill, apply-probe.

## 11. License
AGPL-3.0-or-later (code reused from ApplyPilot/AIHawk). Reused files keep original headers, listed in NOTICE.