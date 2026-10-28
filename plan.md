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
| Scraping ethics | never defeat bot challenges (no fingerprint spoofing, challenge solving, proxies, fake UAs); robots.txt not enforced since 2026-10-25 (maintainer: "do as freehire does"); per-host rate limits and Crawl-delay pacing kept (Wuzzuf search is disallowed and Cloudflare-protected, so the plugin reads its job sitemaps at Crawl-delay 10) |
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

### Phase 8 — Sources ported from freehire (MIT) ✅
Final registry: 124 ATS, 42 aggregators, 18 boards and 48 company plugins, plus Telegram (1),
jobspy (6 sites), regional (Wuzzuf, Forasna) and the generic careers source. Unit suite: 1367 passed, 1 skipped.
Decisions (maintainer, 2026-10-24): port every adapter that works with honest plain HTTP, in
batches; adapters that need freehire's bot-protection layer (tls-client fingerprints,
Scrapling challenge-solving browser, rotating proxies, spoofed Googlebot/app user agents,
ALTCHA proof-of-work) are NOT ported (CLAUDE.md §5.2). Company lists come from a Common
Crawl discovery step plus the user's own list. Aggregator API keys live in the vault with a
Setup "API keys" section. Telegram: t.me/s web-preview reader, freehire's 95 channels plus
user-added (Arabic hiring words in the prefilter). Logic is re-implemented in Python, no
code copied verbatim; NOTICE credits freehire (MIT). Survey: scratchpad freehire-survey.md.
- ✅ F0a Source framework: auto-registry (no shared registry edits), per-module detector
  patterns, shared helpers (403/429 retry-with-backoff, paging), per-source test files
- ✅ F0b Boards table + `linkit discover-boards` (Common Crawl CDX per ATS) + per-run rotation caps
- ✅ F0c API keys in the vault + Setup section + `api_key()` helper for sources
- ✅ F0d Workday: 2,000-cap facet split, 403/429 backoff, details only for unseen jobs
- ✅ F0e Telegram reader, channel table + Setup, Arabic prefilter, link-out to ATS, batched AI extraction
- F1 ATS feed adapters (sources/ats/), shared brief: scratchpad brief-adapters.md
  - ✅ F1.1 adp adpmyjobs applicantstack applitrack appone avature bamboohr beesite betterteam breezy briefhq bullhorn careerplug
  - ✅ F1.2 catsone comeet compleo cornerstone crelate dayforce deel dover earcu
  - ✅ F1.3 emply epam eploy erecruiter factorial freshteam friendwork geekhunter gem gethired gr8people
  - ✅ F1.4 gupy gusto harri hcshiring herp hibob higherme hireclick hireology hiringroom hiringthing hrmanager hrmdirect
  - ✅ F1.5 hrmos humanbit huntflow hurma icims idealtraits inhire ismartrecruit isolvedhire itechart jazzhr jibe jobappnetwork
  - ✅ F1.6 jobscore jobspage jobvite join keka likeit loxo luxoft manatal mindsight mokahr northstone
  - ✅ F1.7 odoo opencats oracle pageup pandape paradox paycom paycor paylocity peoplesoft personio phenom
  - ✅ F1.8 pinpoint potok pyjamahr quickin radancy rapyd recruiterflow recruitingsolutions recrutei rippling scalis selfrecruit senior
  - ✅ F1.9 softgarden solides spark speedrun successfactors talentadore talenthr talentlyft taleo taleobe teamtailor tenstreet traffit
  - ✅ F1.10 trakstar ukg ukgready vention vouch werecruit workablemarketplace workstream wpyoast zoho ashbygraphql
  - not ported (proxy-only, would need a spoofed client): careerspage eightfold enlizt peopleforce cleverstaff clinch neogov, feishujobs (needs a spoofed UA).
- F2 Aggregators (sources/aggregators/, opt-in via sources.enabled)
  - ✅ F2.1 adzuna reed usajobs whatjobs + API-key wiring into sources
  - ✅ F2.2 arbeitnow arbeitsagentur devglobaljobs edjoin empregos eures functionalworks getmanfred getmatch getonbrd
  - ✅ F2.3 getro golangjobs hackernews herkey himalayas jobdanmark jobicy jobnet jobstash jobtech
  - ✅ F2.4 kalibrr landingjobs mycareersfuture nofluffjobs powertofly remoteok remotive remotli schoolspring seek
  - ✅ F2.5 solidjobs teamex tecla themuse topco tyomarkkinatori workingnomads
  - ✅ F2.6 wttj (Algolia index with the site's public key + Referer, per maintainer 2026-10-25)
  - not ported (bypass-dependent): echojobs fourdayweek habrcareer hhru jobleads naukri startupjobs techinasia wellfound
  - not ported (other): trudvsem (needs a Russian root CA); workatastartup (login)
- ✅ F5 Setup UI: list every opt-in source (aggregators, boards, company plugins) with toggles, from a /api/sources endpoint
- F3 Job boards + RSS (sources/boards/, opt-in)
  - ✅ F3.1 builtin instaffo itviec japandev jobboardly jobylon joppy
  - ✅ F3.2 profession pythonorg remotedotcom startupandvc techtree thehub torre work180 + RSS cryptocurrencyjobs jobspresso nodesk weworkremotely
  - not ported (other): aijobs (dead/changed)
  - not ported (bypass-dependent): bayt catho civilservicejobs djinni energyjobline geekjob gradcracker gulftalent infojobs occ vagas wantapply wuzzuf
- F4 Single-company plugins (sources/companies/, opt-in); not ported: metacareers onstrider kontur twogis uber (bypass), airswift tenml (no jobs), alfabank tbank tochka ptsecurity (need a Russian root CA)
  - ✅ F4.1 alibaba alignerr amazon apple aviasales avito bairesdev dassault dataart dodo domclick
  - ✅ F4.2 emagine garena google halyk ibm jettycloud kaspersky kaspi kuper lamoda lesta lumenalta
  - ✅ F4.3 magnit megafon meituan micro1 mts mtslink orion ozon rostelecom rwb sber
  - ✅ F4.4 selectel staffy tbank telegramcareers tencent tochka uzum vk x5 yandex yandexcrowd
- ✅ F6 Cleanup: jobboardly is an ATS plugin; `ats` is set from the apply link (ats_detector) for aggregator/board/company stubs so apply handlers route correctly; private helpers merged into `sources/common.py`, `parsing.py`, `tasks.py` and `aggregators/keys.py`; `Http.post_form` + public raw response; per-host slow rates (myworkdaysite 1, higherme 1/3, join 1.5, workstream 1); Common Crawl older-collection fallback; full suite and a browser check of the Setup sources list

### Phase 9 — Debt (offline, fixture-tested) ✅
Maintainer (2026-10-25): work the handoff "Known issues" list; generic sign-up is out of scope
(sign-in/sign-up pages keep parking until a supervised live session). AI provider keys in the
vault: not started, needs the maintainer.
- ✅ D1 Live run: per-job screenshot event over the WebSocket instead of 3 s file polling
- ✅ D2 Generic form agent: controls inside same-origin and cross-origin iframes
- ✅ D3 Arabic UI: server park messages and source keys shown translated/labelled
- ✅ D4 Jobs page: readable titles at phone width; clicking a job while the drawer is open switches it
- ✅ D5 Gmail IMAP: find the spam folder by the \Junk special-use flag, not the English name
- ✅ D6 Careers browser fallback: links to a known ATS are re-routed to that ATS plugin
- ✅ D7 Unit tests use an in-memory keyring (failed without an OS keyring backend)

### Phase 10 — Trust filter: ghost and scam jobs ✅
Goal: stop spending the user's time and AI tokens on scam postings and ghost jobs (real
company, stale or never-filled opening), with no extra AI calls. Research (2026-10-25, code
read, not READMEs): tobiasverified/ghost-job-detector (MIT: vagueness score, ATS first-published
age), Iron-Mark/Hackathon-HireProof (ISC: scam vocabulary, text normalizer, domain mismatch,
floors + signal trace), Farhan89082 (age tiers, fuzzy repost, vague titles; ideas only),
Arya185 (MIT: fee/contact phrase lists). Rejected: every ML model (English-only 2014 EMSCAD,
scam-only), aliabdm (one LLM call per job, no rules), paid/search APIs. ghostbust.us: DNS fails.
Decisions (maintainer, 2026-10-25):
- Two separate scores per job, `scam` and `ghost` (0-100), each with a signal list
  `{code, weight, evidence}`, stored in `jobs.data["trust"]`; EN + AR rules.
- Scam high (>= 65) -> `filtered_out` with a coded reason; "Not a scam" restores and
  allow-lists the company; "Report" adds it to the blacklist.
- Ghost likely (>= 50) -> tier `low` (never AI-scored or auto-applied unless low opt-in).
  Setting "Also filter out ghost jobs above N" (default off, N = 50) plus a bulk action on the
  jobs page.
- Network: only the ATS liveness re-check before applying (vanished -> skipped). No RDAP/DNS.
- AI: optional `red_flags` field in the existing batched score prompt; can raise, never clear.
- Runs inside the rank stage after hard rules and before embeddings, so dropped jobs cost nothing.
- Reused MIT/ISC files keep their notices in NOTICE; lists are rewritten, not pasted.
Decisions made by the orchestrator: verdict bands scam 35/65, ghost 35/50 (from the
references, untuned); repeat sightings go in a new `job_sightings` table (store_page drops
duplicates today); salary outlier = >= 2.5x the median of stored jobs with the same title family
and currency.
Execution tasks:
- ✅ G1 Sightings: `job_sightings` (job_id, run_id, seen_at, url) + migration; store_page records
  a sighting for every duplicate; first_seen/seen_runs helpers
- ✅ G2 `matching/trust/normalize.py` (NFKC, homoglyphs, leetspeak, Arabic letter variants,
  clause negation with coercion override) + `scam.py` rules, floors and trace (EN + AR)
- ✅ G3 `matching/trust/ghost.py`: age (posted_at, ATS first-published, first sighting), reposts
  and still-open across runs, vagueness port (EN + AR), vague titles, company role surge,
  missing salary (small)
- ✅ G4 Wire into rank: thresholds, filtered_out/low with codes, settings section, restore/report API
- ✅ G5 UI: badge in the jobs table, signals in the drawer (translated), Not a scam / Report,
  ghost cut-off setting + bulk action
- ✅ G6 ATS liveness check in the apply runner before tailoring
- ✅ G7 Optional `legit` (ok/suspicious/scam) and `trust_flags` in the batched score prompt + schema
- ✅ G8 Docs: NOTICE, CLAUDE.md §5.3, docs/, handoff

### Phase 11 — LinkedIn hiring posts 🟡
Goal: find jobs announced as LinkedIn posts (HR/company profiles) and apply through the
email or form link they give. Reference: pritamdharme/linkedin-hiring-post (no license: ideas
only — saved session, content-search URL, post markers, HTML dump on zero posts).
Decision (maintainer, 2026-10-26): LinkedIn hides results from automated Chrome. playwright-stealth
didn't help, so the maintainer chose the stealth-browser-mcp approach (real installed Chrome launched
without automation flags, Playwright attached over CDP) for ALL browser automation; playwright-stealth
is removed. Challenges, login, proxies and fingerprint/TLS spoofing stay forbidden.
Decisions (maintainer, 2026-10-25):
- Opt-in source, off by default, ToS/ban-risk warning, low caps (5 keywords, ~60 posts each,
  past week, one run a day). Dedicated `linkedin` Chrome profile; the user signs in once in a
  visible window, scraping then runs headless (Setup switch to run headed). Logged out or a
  security check -> stop the source for that run and notify; never automate login, never
  bypass a challenge, never comment, DM or react.
- Posts with an ATS link -> that ATS (no AI); others -> batched AI extraction (10 per call):
  role, company, location, apply method (email | form | link), email, link. Posts without an
  email or link ("DM me", "comment") and job-seeker posts are dropped.
- Email applications via Gmail SMTP with the app password already in the vault: short cover
  email grounded only in CV/profile + tailored CV PDF. Dry run writes an .eml preview only.
  Live follows "Submit without asking" (else confirm in the Action Center, editable).
  Caps: 15 emails/day, never the same address twice. A sent email = applied (by email); the
  sent message is the proof.
- Form/link posts go through the existing generic form agent.
Interface (orchestrator): `sources/linkedin_posts/` package — `post.py::RawPost` (frozen
dataclass: urn, url, author, author_url, headline, posted_text, text, links, emails,
scraped_at), `extract.py` (RawPost list -> JobStub list), `scrape.py` (Playwright -> RawPost),
`__init__.py` Source (kind "social", opt-in). Email apply: `apply/email_send/`.
Execution tasks:
- ✅ L1 `linkedin` profile key, sign-in (headed app browser) + session check API, `linkit linkedin capture`
- ✅ L1b playwright-stealth on the LinkedIn profile (superseded by S1, removed)
- ⬜ L2 Scraper: unfiltered search URL + `load_more` pager (live-checked), `post.keep_recent` (window only past 100 posts), per-post extraction, login/checkpoint stop, zero-post HTML dump (needs the maintainer's captured page)
- ✅ L3 RawPost model, hiring/seeker filter, ATS routing, batched AI extraction prompt, stubs, trust tweaks
- ✅ L4 SMTP sender (vault creds) + "send test email to myself" API
- ✅ L5 Email apply channel in the runner: compose, dry-run .eml, confirm park, caps, recipient dedupe, evidence
- ✅ L6 UI: Setup LinkedIn posts section, Action Center email preview/edit, post info in drawer
- ✅ L7 Docs, CLAUDE.md §5.2/§5.5, handoff
- ✅ S1 Real-Chrome launcher (no automation flags) + Playwright over CDP for all browser work
- ⬜ S2 LinkedIn read path on nodriver (only if S1 still gets empty results)
