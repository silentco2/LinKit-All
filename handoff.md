# Handoff — LinKit All

Written 2026-10-16 (updated 2026-10-25) for the next agent or developer. Read in this order: `CLAUDE.md` (rules,
binding), `plan.md` (roadmap and every decision, including "Decisions made by the
orchestrator"), then this file (current state and next steps). Ask the maintainer before
changing a decision in either file.

## TL;DR

- Phases 0-8 are built, except the items blocked on the maintainer (see "Needs the
  maintainer"). Every task in `plan.md` is done or marked blocked.
- Phase 8 (sources ported from freehire) is built too: see "Phase 8 - sources from freehire".
- Phase 9 (debt D1-D7) is done; what remains of the debt is in "Known issues and debt".
- Phase 10 (trust filter: scam and ghost scores, offline, EN + AR, in the rank stage; ATS liveness
  check before apply; optional AI legit flags) is done. See `docs/trust.md`.
- Phase 11 (LinkedIn hiring posts + apply by email) is built except **L2, the Playwright post
  scraper**: it is blocked until the maintainer captures a LinkedIn search page
  (`linkit linkedin capture`). Everything else works: sign-in and session check, post filter, ATS
  routing, batched AI extraction, SMTP sender, email apply (dry-run .eml, confirm, caps), UI.
  See `docs/linkedin-posts.md` and `plan.md` Phase 11.
- The unit suite passes (`uv run pytest tests/unit`: 1711 tests collected after Phase 11; 1640 passed, 2 skipped
  before it, the real Tectonic compile),
  ruff and mypy are clean, `npx ng build` is clean.
- Nothing has ever been submitted for real. Apply runs in dry-run mode by default and has
  only been exercised as dry runs on live forms plus offline e2e tests with a fake submit.
- User docs are in `docs/` (MkDocs Material); `uv run mkdocs serve` previews them.

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
- Tectonic is not installed (the one skipped test is the real LaTeX compile).
- The project also runs in a Linux cloud container: no Google Chrome or OS keyring there
  (unit tests use an in-memory keyring); e2e tests can use Playwright's bundled
  Chromium/headless shell under `/opt/pw-browsers`.

### Gotchas that cost time

1. **The Claude desktop app is MSIX-packaged.** Anything the agent's shell installs or writes
   under `%APPDATA%` / `%LOCALAPPDATA%` is redirected to
   `%LOCALAPPDATA%\Packages\Claude_pzs8sxrjxfjjc\LocalCache\...`. It works for the agent but
   is invisible to the maintainer's terminals (example: a uv Python install broke `.venv` for
   the user). Install interpreters or global tools, and run anything that must land in the real
   data dir, through the Terminal panel (`run_in_terminal`). Writes under `D:\` are fine.
   Consequence: the agent's shell **cannot see the real LibreOffice bundle**. For tests that
   need it, install it into a D:\ data dir:
   `LINKIT_DATA_DIR="D:\LinKit All\build\lo-test-data" uv run linkit install-libreoffice build/lo/<zip>`
   and run those tests with the same `LINKIT_DATA_DIR`.
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
6. **`uv run` cannot replace `linkit.exe` while a server is running** (Windows file lock).
   Stop the server first, or use `uv run --no-sync ...`.
7. **Do not run test processes in parallel**: LibreOffice tests (and anything using the same
   LibreOffice profile) collide. Run `uv run pytest` once at a time.

### Scratch data (all gitignored under `build/`)

- `build/smoke/data` — a working data dir with about 2,100 real jobs (Stripe, Airbnb,
  OpenAI, Palantir, Notion, plus Cairo jobs from LinkedIn, Indeed, Bayt and Wuzzuf), a test
  profile "Jane Doe" with a generated CV, a search config and the downloaded embedding model.
  Use it with `LINKIT_DATA_DIR`.
- `build/forms` — saved live application pages (Greenhouse embed for Airbnb, Lever for
  Palantir, Ashby for OpenAI) with field dumps.
- `build/dryrun` — the last dry run against those three live forms, with screenshots.
- `build/lo`, `build/lo-test-data` — the LibreOffice zip and a D:\ data dir with it installed.
- Throwaway inspection scripts lived in the agent's scratchpad (read-only form inspector,
  live dry-run harness); recreate them from the patterns in `tests/e2e/test_apply_lever.py`.

## How to run

```bash
uv sync
uv run linkit doctor                      # Python, LibreOffice, Chrome, Codex, Claude, Tectonic
uv run linkit                             # UI at http://127.0.0.1:8765 (same as `linkit serve`)
uv run linkit profile import profile.json # docs/profile.example.json
uv run linkit search import search.toml   # docs/search.example.toml (incl. [schedule])
uv run linkit run discover|enrich|rank|score|apply   # one stage; `discover --new` starts a new run
uv run linkit status ; uv run linkit jobs --tier mid
uv run linkit tailor jd.txt               # debug: red-line patches for one job description
uv run linkit ai-check --provider codex_cli
uv run mkdocs serve                       # user docs preview (mkdocs build --strict must be clean)
cd frontend && npm ci && npx ng build     # UI -> src/linkit_all/static/browser
```

- **Arabic UI**: the language toggle is in the app shell; one build serves both languages
  (runtime dictionary in `frontend/src/app/i18n/{en,ar}.ts`, RTL handled in `locale.ts`).
- **Local models**: setup wizard, AI step, "Local model" (Ollama / LM Studio via `api_base`
  on the `litellm` provider).
- **Schedule**: "Schedule" section on the Live run page, or the `[schedule]` table in `search.toml`
  (days, times, `new_run`). Needs the app running; a scheduled run does all five stages and is
  a dry run unless live applying is on.

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
    config.py       Settings (LINKIT_* env): data_dir, provider (codex_cli|claude_cli|litellm),
                    model, tailoring thresholds, embedding model, dev_origins
    models.py       runs, jobs, job_events, llm_cache, profile (+answers JSON), locked_facts,
                    tailored_cvs, search_config, source_checkpoints, answer_bank, action_items,
                    vault tables
    state.py        ALLOWED transitions; transition() writes job_events
    search.py       SearchConfig: search, sources, filters, matching, apply, ai, schedule sections
    scheduler.py    APScheduler (SQLAlchemy job store) + desktop notifications; skips a tick
                    if a run is already going
    profile.py      profile fields, CV upload checks (DOCX/ODT/PDF/LaTeX), JSON import
    runs.py, db.py, log.py (redaction), tools.py (find soffice/chrome/tectonic; bundled LO first)
    migrations/     Alembic; runs automatically in init_db()
  providers/        LLMProvider.complete(prompt, schema); claude_cli, codex_cli, litellm_api;
                    prompts/*.j2 (json_output, json_retry, ping, tailor, score, answer,
                    cover_letter, ...)
  sources/linkedin_posts/  post (RawPost), extract (hiring/seeker filter, ATS routing, batched AI
                    extraction -> JobStub), session (linkedin Chrome profile, session check,
                    page capture); scrape.py (L2) not written yet
  sources/          base (JobStub, Task, Source), http (rate limits + retries + Crawl-delay
                    pacing), text (html->text, URL/company normalization, hash),
                    store (Deduper), runner (discover, enrich), ats_detector,
                    greenhouse, lever, ashby, smartrecruiters, recruitee, workable, workday
                    (cxs), jobspy_sites, wuzzuf, forasna, careers (generic careers pages),
                    jsonld
  core/sightings.py job_sightings table: a row per time a job is seen in a run (age, repeats)
  matching/         rules (hard filters, seniority), rank (Embedder, rank_jobs), score (AI tiers,
                    legit/trust_flags), trust_stage (runs the trust check in rank)
    trust/          normalize (NFKC, homoglyphs, leetspeak, Arabic variants), scam, ghost:
                    offline scores 0-100 with {code, weight, evidence} signals in jobs.data["trust"]
  tailor/           docx/segments, latex/ (TexSoup text nodes), patches (rules),
                    render/{libreoffice,latex}.py (Tectonic), verify/layout,
                    pipeline (tailor_docx, tailor_for, tailor_job; ODT/PDF/LaTeX entry; reuses an
                    existing tailored CV)
  reports/          per platform / board / run, over time, funnel; CSV + PDF export
  apply/
    answers.py      Question, ApplicationAnswers, sensitive_category(), sensitive/standard
                    answers, option pickers, resolve_static()
    assist.py       AnswerBank (embedding match), ai_drafts, write_cover_letter,
                    answer_questions() (full resolution)
    form.py         page script that tags question containers (data-lk) and controls
                    (data-lk-input); fill(); lost_values() refill check
    browser.py      persistent Chrome profile dir per ATS, live screenshot file (written every
                    3 s while applying), app-browser session helpers
    handlers/       base (Handler, JobInfo, confirmation/CAPTCHA/error checks), greenhouse,
                    lever, ashby; HANDLERS registry
    agent/          generic AI form agent: snapshot.js (control snapshot), field-map schema,
                    one-page step; multi-page loop lives in the runner
    vault/          AES-GCM per secret, Argon2id key from the passphrase, keyring cache,
                    lock/unlock, export (re-asks the passphrase)
    email_verify/   IMAP (Gmail app password from the vault): code/link regex first, AI
                    fallback; matches sender domain + time window
    accounts/       password generator per site rules, save-to-vault-before-sign-up, login reuse
    email_send/     SMTP sender (Gmail/Yahoo, vault app password), test email
    email_apply.py  compose cover email (body from the model), caps, recipient dedupe
    runner.py       Applier (persistent Chrome per ATS), pick_jobs (caps), apply(),
                    click_submit() guard, apply_jobs(); handler or generic agent; account gate;
                    ApplyBlocked, DryRunViolation
  api/              app (factory, lifespan, SPA fallback, serve), routes (all /api endpoints),
                    runner (PipelineRunner, one run at a time), events (EventBus + log sink),
                    security (LocalOnly middleware)
  static/browser/   built Angular app (gitignored, shipped in the wheel via hatch artifacts)
frontend/src/app/   app.ts (shell, nav, badges, language toggle), api.ts, live.ts (WebSocket),
                    types.ts, i18n.ts + i18n/{en,ar}.ts (runtime dictionary), locale.ts (language,
                    RTL), pages/{setup,jobs,job-detail,review,live,report,actions,answers,vault}.ts
                    (inline templates)
docs/               MkDocs Material user + developer guide (mkdocs.yml at the root)
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
- **Account gate**: the generated password is saved to the vault *before* the sign-up click.
  A dry run never touches sign-up forms (the outcome
  says an account would be created). Live mode creates accounts when a form needs one; the
  application itself still waits for confirmation. One vault entry per (ats, tenant).
- **App browser** ("Open in app browser" in the Action Center): opens the user's own window on
  the same Chrome profile, fills nothing automatically, and runs are refused while it is open
  (the profile can only be held by one browser).
- **Generic agent**: the model returns a field map; our code fills, validates and clicks.
  Answers still go through the answer engine (sensitive rules apply). A job becomes `applied`
  only with confirmation wording on the page; otherwise it parks or fails.
- **Applied only on proof**: a job becomes `applied` only when the ATS confirmation page
  text is seen (or the user says "applied by hand"). Otherwise: Action Center or `failed`
  with a reason. Screenshots before submit and after; a Playwright trace on failure.
- **robots.txt is not enforced** (maintainer, 2026-10-25): no source refuses a URL because of it.
  `Http.allowed(url)` always returns True; on the first request to a host it reads robots.txt
  once, only to apply that host's `Crawl-delay` (`sources/http.py`). Per-host rate limits stay.
  Bot protection is never bypassed: no TLS-fingerprint spoofing, challenge-solving browsers,
  rotating proxies or fake crawler/app user agents.
- **CAPTCHAs are never solved** or bypassed (CapSolver dropped); they park for the user, who
  solves them in the open browser, then Retry. Never defeat bot challenges or disguise a
  client (Naukrigulf, SmartRecruiters).
- **Local only**: the server binds to 127.0.0.1; `LocalOnly` rejects foreign Host headers and
  cross-origin writes and WebSockets. Screenshot endpoints serve files only from the data dir.
- **Privacy**: never log passwords, tokens or CV text (loguru patcher redacts secrets; log ids
  and counts). No telemetry. Only the chosen AI provider sees CV and job text.
- **Tests**: no live-site calls in CI; e2e apply tests intercept every request. Never submit
  a real application without the maintainer's explicit go-ahead.

## What's built (by phase)

| Phase | State | Notes |
|---|---|---|
| 0 Init | done | CI matrix in `.github/workflows/ci.yml` (Python + frontend build) |
| 1 Core | done | providers verified live with Codex and Claude from the maintainer's terminal |
| 2 Discovery + matching | done | live: 5 company boards -> 2,075 jobs in 12 s; Cairo searches on LinkedIn/Indeed/Bayt; Wuzzuf via sitemaps |
| 3 UI v1 | done | setup wizard, jobs, review, live run, report checked in the browser with real data |
| 4 Apply v1 | done | `c5c5494` wizard steps, `08b8451` answer bank API, `4b94e9a` Action Center, `3b1bad1` Live run apply, `378d340` answer bank page; dry-run verified on live Airbnb/Palantir/OpenAI forms |
| 5 Apply v2 | partly | `474c270` runner checks handler before tailoring; `a6ac0e5`/`34986c6` vault core + UI; `40392b6`/`69a826e` IMAP verification + email step; `65fbc5f` account gate; `d6ff3bd`/`8f8acdf` SmartRecruiters, Recruitee, Workable, Workday discovery; `dfee500` runner uses the server's vault. Handlers for Workday/iCIMS/Taleo/SuccessFactors/SmartRecruiters and LinkedIn/Indeed apply: blocked |
| 6 Generic | done except Naukrigulf | `93cd3be`/`48c8b27` careers source (batched AI extraction); `ad27af6`/`685bd7c` generic form agent + runner fallback; `4903956` Forasna; `9239b3e` RFC 9309 robots matcher |
| 7 Later | partly | `276fa96` ODT/PDF CVs + reports; `bf15f7b` scheduler, notifications, LaTeX CVs; `49a422f` local models; `2403f4f`/`0fb0c7c` Arabic RTL UI; `5fd2425` MkDocs docs; `093780f`/`3908a83`/`0353d50` CLAUDE.md gap fixes (app browser, red-line, live view, low-tier opt-in). Outlook OAuth, macOS/Linux bundles, release: pending |
| 8 freehire sources | done | 124 ATS, 42 aggregators, 18 boards, 48 company plugins, Telegram, board discovery (`F0a`..`F6b`, since `ad1241d`); fixtures only |

## Phase 8 - sources from freehire

Ported from [freehire](https://github.com/strelov1/freehire) (MIT, credited in `NOTICE`),
re-implemented in Python on plain honest HTTP. Plan and not-ported lists: `plan.md` Phase 8.

- **What exists** (`uv run --no-sync python -c "from linkit_all.sources import registry; ..."`):
  124 ATS plugins (`sources/ats/`), 42 aggregators (`aggregators/`), 18 job boards and RSS feeds
  (`boards/`), 48 single-company plugins (`companies/`), `telegram.py`, plus the older jobspy,
  Wuzzuf/Forasna and careers sources. `sources/__init__.py` scans the packages: a new plugin
  needs no registry edit.
- **Telegram**: public `t.me/s/<channel>` previews, 95 default channels plus the user's own,
  Arabic hiring words in the prefilter, links to a known ATS skip the AI, other posts go to the
  AI in batches.
- **Discovered boards**: `boards` table; `linkit discover-boards` asks Common Crawl's index for
  boards on each ATS (falls back to older collections when the newest answers 404);
  `sources.use_discovered_boards` + `boards_per_run` crawl the oldest-crawled ones each run.
- **API keys** (Adzuna, Reed, USAJobs, WhatJobs): stored in the vault (`core/api_keys.py`),
  edited in Setup, read by plugins through `sources/aggregators/keys.py`.
- **Workday**: facet splitting around the 2,000-result cap, 403/429 backoff, details fetched only
  for unseen jobs.
- **ATS routing**: a stub from an aggregator, board, company plugin or Telegram whose apply link
  is on a known ATS gets that `ats`, so the right apply handler runs; `source` keeps the origin.
- **Enabling**: ATS plugins run from the companies list (or discovered boards) and need no switch.
  Aggregators, boards, company plugins and Telegram are opt-in: Setup, "More job sources" (backed
  by `GET /api/sources`), or `sources.enabled` in `search.toml`.
- **Writing one**: `docs/development.md` ("Adding a job source"), with the shared helpers in
  `sources/common.py`, `parsing.py`, `tasks.py` and `aggregators/keys.py`.
- **Safety**: no bot-protection bypass (no TLS spoofing, challenge solvers, rotating proxies or
  fake crawler/app user agents); robots.txt is not enforced by maintainer decision, Crawl-delay
  and per-host rate limits are. Slow hosts: Wuzzuf/Forasna 1 per 10 s, LinkedIn 1 per 2 s,
  HigherMe 1 per 3 s, Workable/Workday/Workstream 1 per s, Join 1.5 per s.
- **Gaps and debt**: every source is tested with fixtures only, and many fixtures were built by
  hand from freehire's test samples, so the first live runs may show API drift. megafon, yandex
  and ozon are slow. Some company names are placeholders where the API does not name the
  employer. Adzuna's monthly call cap is not tracked. jobspy and the ATS APIs were never
  robots-checked anyway. Not ported (reasons in `plan.md`): bypass-dependent sources, Russian
  root-CA sites (trudvsem, alfabank, tbank, tochka, ptsecurity), workatastartup (login), aijobs
  (dead). wttj is ported (public Algolia key + the site's Referer, maintainer 2026-10-25).

## Needs the maintainer (blockers)

1. **First supervised live application** (Live on, confirm each). Nothing real has been sent.
2. **Saved rendered pages** so handlers can be written: Workday, iCIMS, Taleo, SuccessFactors
   (forms sit behind sign-up), SmartRecruiters (DataDome-protected, client-rendered), and a
   sitemap slice + job pages for Naukrigulf (its edge drops non-browser clients; we never
   disguise the client). Until then those sites use the generic agent or are unsupported.
3. **A supervised session for real account creation + Gmail IMAP verification** (Gmail app
   password); the account gate and email code are tested offline only.
4. **Install Tectonic** so the real LaTeX compile test can run (the one skipped test).
5. **Outlook OAuth** (needs an Azure app registration).
6. **macOS/Linux LibreOffice bundles** (need those OSes or CI).
7. **GitHub repo + PyPI release** (outward-facing: needs the maintainer's go-ahead).

8. **A captured LinkedIn page** so the post scraper (L2) can be written:
   `linkit linkedin capture --keywords "hiring python developer"` after signing in from Setup.
   Review the file first: it is a copy of your own LinkedIn page.
9. **A first supervised live email application** (Live on, confirm each; send the test email
   to yourself first).

## Resolved: robots.txt scope

Maintainer decision (2026-10-25, replaces the 2026-10-16 one): robots.txt is not enforced
anywhere; Crawl-delay pacing and per-host rate limits stay. Recorded in CLAUDE.md §5.2.

## Next steps

1. (Done) robots.txt scope decided — see "Resolved: robots.txt scope".
2. Run the first supervised live application with the maintainer (item 1 above), then
   real account creation + IMAP (item 3). Expect to fix handler details found live.
3. As the maintainer supplies saved pages: write the Workday/iCIMS/Taleo/SuccessFactors/
   SmartRecruiters handlers (plugin + fixture + tests each), then Naukrigulf.
4. Remaining debt is listed in "Known issues and debt".
5. Release work once the maintainer says go: GitHub repo, CI on three OSes, PyPI.

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

- LinkedIn markup changes often: the post selectors (once L2 exists) will need upkeep. LinkedIn runs headless by
  default (real UA + client hints, fitted screen); the Latest + Past week filters gave 1 post, so
  search is unfiltered and the window is applied to scraped posts past 100. Seeker-tag posts ("open to work")
  that also contain hiring words are dropped. The email greeting heuristic can misjudge a
  company address versus a person.

- Trust filter thresholds (scam 65, ghost 50, bands 35) come from the reference projects and
  are untuned; they need tuning on real runs.
- Greenhouse `posted_at` may be `updated_at` when `first_published` is missing, so a job's age
  is under-counted.
- `company_domain_hint` (`data["company_url"]`) is not populated by most sources, so the
  domain-mismatch check compares with the company name only.
- The bulk ghost cut-off ("Filter out ghost jobs now") skips already-scored jobs, and that
  cannot be reversed automatically.
- The Report confirm dialog was not exercised in a browser test.
- ghostbust.us was unreachable (DNS) during the trust research, so it was not reviewed.
- CLAUDE.md is at its 200-line cap (tighten something else rather than grow it).
- `SearchConfig` also holds `ai`, `apply` and `schedule` settings (it's really "preferences");
  renaming would touch the API, UI and saved data, so it was left.
- Dedupe collapses same-title openings at the same company and location (fine while one job
  per company is the default).
- Wuzzuf fetches only slugs containing every word of a query (each fetch costs 10 s).
- Forasna fetches all numbered sitemaps each run (about 80 s).
- Workday: `postedOn` is relative text ("Posted 3 Days Ago"), and the list may cap the total
  at 2,000.
- Careers browser fallback (`sources/browser_extract.py`) is live-untested: only fixtures via route
  interception. Links it finds on a known ATS board are handed to that ATS plugin (its JSON API
  replaces the generic stubs for the board; a failing board keeps them), tested only with fakes.
  JS-only job pages on unknown sites still keep the listing's title and get no description.
- There is no generic sign-up (sign-in pages park).
- A combobox with no fixed options (city, country) picks the first suggestion after typing.
- Live submission is untested against real sites (CAPTCHA behavior unknown).
- `two_factor` and captcha resolution is manual: "Open in app browser", solve, then Retry.
- ODT/PDF/LaTeX CV path skips LaTeX `\input` projects and package macros like `\cventry`.
- Job-aggregator API keys are in the vault; AI provider keys are still env-only.
- When `ApplyBlocked` fires (AI limit, LibreOffice missing) the rest of that run's jobs wait
  for the next run.
- Translated (coded) messages cover apply and Action Center only; matching/rank/score/tailor/
  source event text, run outcomes ("no form handler"), `ApplyBlocked` and the AI-limit pause
  reason are still English in the Arabic UI. The generic agent's fail reason is model free text.
- Parallel apply browsers share one live screenshot file; the latest frame wins (the event
  names its job).
- Below 1280px the open job drawer covers the list; close it to pick another job.
- Starlette's TestClient warns about httpx (`httpx2`); harmless.

## Conventions

- Small focused commits; message body explains what and why; end with
  `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (use the attribution the
  session's system reminder gives). One commit per reviewed task.
- Keep the code lazy and boring: reuse what exists, stdlib first, no speculative
  abstractions; mark deliberate shortcuts with a `ponytail:` comment naming the ceiling.
- Type hints everywhere (mypy strict); a test for every new logic path; new source or
  handler = plugin + fixture + tests; fixtures are trimmed copies of real responses.
- Prompts live in `providers/prompts/*.j2`, never inline; every AI output is validated
  against a Pydantic schema.
- Update `plan.md` task status and this file when a decision or state changes.
