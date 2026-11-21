# Competitor analysis: Job-Ops (what to borrow)

## Context

Job-Ops (github.com/DaKheera47/job-ops, release 0.14.0, commit `7fac74f`, 2026-10-27) is a
self-hosted TypeScript app (Node + React + SQLite, Docker). It claims 800+ users.
Pipeline: search about 15 boards -> AI score 0-100 -> rewrite CV sections -> PDF -> the user applies
by hand -> Gmail tracking. **It never applies.** Its README says auto-apply gets you blacklisted.

License: AGPLv3 **+ Commons Clause**. Copy no code. Reimplement ideas only, in Python.
Reference clone (read-only): `C:\Users\Osama\AppData\Local\Temp\claude\e9ce47fd1ff9ee32\e3d6e139-0784-4acf-b0f8-057ff49ee41b\scratchpad\jobops-src\repo`.

## Where we are already ahead

| Area | Job-Ops | LinKit All |
|---|---|---|
| Applying | none, the user applies by hand | handlers + AI form agent + accounts + email apply |
| Sources | about 15 extractors | 300+ plugins (ATS APIs, aggregators, boards, companies, Telegram) |
| Tailoring | AI rewrites summary, headline, skills and project picks into a Reactive Resume JSON | word-level patches, layout kept, locked facts, pixel diff |
| Trust | none | scam and ghost scores |
| Privacy | Umami analytics on by default; map calls OpenStreetMap | no telemetry, offline datasets |
| Languages | English UI | English + Arabic |

## Ideas worth borrowing (ranked)

### A. Real gaps, high value

**A1. Location filter drops jobs in the user's own city (bug, verified).**
`matching/rules.py:64` is a substring test against the place label. With the place "Cairo, Egypt"
these job locations are all rejected as "not in your locations":
`Cairo` · `Cairo, EG` · `Giza, Egypt` · `New Cairo, Cairo Governorate, Egypt` · and for Dubai, `Dubai`.
Job-Ops matches centrally against expanded place names (city, nearby towns, country).
Fix:
1. Parse the job location with `core/geo.py` (city, country, ISO2, aliases like `EG`, `UAE`).
2. A job passes when its city matches a chosen city, or a chosen place is country-level and the country matches.
3. Optional radius: add lat/lon to the bundled `data/cities.json` (GeoNames has them, still offline), then accept cities within N km of a chosen city.
Effort: steps 1-2 about 2 hours, radius about 1 day.
**Status 2026-11-20: steps 1-2 done** (`geo.locate`, `rules.at_place`, tests in `test_matching.py`).
`Cairo`, `Cairo, EG`, `New Cairo, …`, Arabic names and `Dubai` for a UAE place now pass.
**Step 3 done too:** `cities.json` carries coordinates (`g`, 2 decimals), `geo.distance_km`,
setting `filters.radius_km` (default 40 km, Settings > Jobs & places). Giza (7 km) and
6th of October City (33 km) now count for Cairo; Alexandria (180 km) does not.

**A2. Add one job by link, text or a list of links.**
Job-Ops has "Add a job": a link, pasted description, text PDF, or up to 25 URLs.
We only add whole sources (`/api/sources/add`). A user who finds a job alone cannot send it into
the pipeline. Fix: `POST /api/jobs/add` runs `ats_detector` -> that plugin's `fetch_details`, or else
the generic extractor. The job enters at `enriched`, skips the hard rules (the user picked it),
keeps the trust check, then goes through scoring and the tiers as usual. About 1 day.
**Status 2026-11-20: done** (`sources/manual.py`, `POST /api/jobs/add`, Jobs > "Add a job",
`test_manual_jobs.py`). Up to 25 links, read like a careers-page job (JSON-LD, else heading +
text; no AI), or one link plus pasted text when the page cannot be read. Source "manual"; hard
rules, one-per-company and off-title trash skip it. A job a rule dropped earlier comes back.
A posting saved as PDF fills the paste fields (`POST /api/jobs/pdf-text`, PyMuPDF; scans are refused, no OCR).

**A3. Evidence-checked job facts in the score call.**
Job-Ops' scorer also returns `jobPatches`: missing salary, work mode, location, level, deadline,
each with an exact excerpt from the posting. Code checks that the excerpt is in the posting and
holds the value (numbers, currency symbols). Only then is the patch accepted.
For us: most boards leave work mode and salary blank, so the hard rules pass them on purpose.
Re-run `rule_violation` after scoring with the checked facts. Then an on-site job in the wrong city,
or one below the salary floor, stops before Apply. Fits "AI can raise, never clear": a fact can only
tighten the filter. Same verbatim check style as `core/infer.py`. About 1 day.
**Status 2026-11-20: done** (`matching/facts.py`, `score.j2`, `score.py`, `test_job_facts.py`).
The score call reads work mode, location and salary only for jobs missing them. Code keeps a fact
when its quote is in the posting and holds the value (mode words, place name, every number,
currency code or € £ ₹, period word). A kept fact that breaks a hard rule sends the job to the low
tier (`fact_rule`, reason shown as that rule), never auto-applied, not even with the low opt-in.
Hand-added jobs are not asked. Level and deadline left out: the rules read level from the title,
and deadlines have `matching/deadline.py`. Limit: such a job is not re-checked if filters loosen later.

**A4. Anti-"AI tell" guard on all AI prose.**
Job-Ops has a "Stop Slop" option and do-not-use terms. Our prompts (`cover_letter.j2`,
`application_email.j2`, `answer.j2`) have no such rules. For an auto-apply tool, sounding automated
is the main risk. Fix: a short banned-phrase list ("I am excited to", "delve", "passionate about",
"I hope this finds you well") plus no em dashes. Check after generation, retry once, then
replace or drop what still matches. Rules only, no AI. About half a day.
**Status 2026-11-20: done** (`apply/prose.py`, prompt include `_plain_words.j2`, `test_prose.py`).
Cover letter and application email retry once when a giveaway shows; every AI text (also
free-text answers and follow-ups) then gets `clean()`. Option answers are never changed.

### B. Worth doing, needs a decision or has a risk

**B1. Visa sponsor registers (UK, Netherlands, Canada, US H-1B).**
Job-Ops searches official registers and marks matching employers.
For us: a job in one of the user's `visa_countries` with a register match gets a "Sponsor on register"
label and a small rank boost (never a promise of sponsorship).
**Maintainer decision:** CLAUDE.md §2 allows only one online refresh (FX rates). Options:
(a) bundle a snapshot at release time, or (b) allow a refresh that downloads only the public registers.
Check sizes first (the UK CSV is about 10 MB).
**Done 2026-11-20, option (b)** (`core/sponsors.py`, `test_sponsors.py`): UK register (~133,000
employers), Dutch IND register (~13,000), US H-1B data (newest year, ~30,000), Canada positive
LMIA (last 4 quarters, ~26,000; .xlsx read with lxml, no new dependency). Refreshed at run start,
at most weekly, only for the user's visa countries; a failure keeps the old copy. Exact match after
dropping legal suffixes; "t/a" and "DBA" names count. A job in a visa country at a listed employer
shows a "Visa sponsor" badge and gets +0.05 local rank; nothing else changes.
CLAUDE.md §2 still says the FX refresh is the only one: the maintainer updates that line.

**B2. Source health probe.** Job-Ops has `GET /api/:source/health`: a live search with 1 result,
cached for 1 hour. We have 300+ plugins and a broken one silently returns 0 jobs.
Add `linkit source-check [name]` plus an OK/broken mark in the Sources list. About half a day.
**Done 2026-11-21** (`sources/health.py`, table `source_health` + migration, `test_source_health.py`):
runs record jobs and errors per switched-on source and company entry (`Task.entry`); "Check
sources now" / `linkit source-check` probe one page live (1-hour cache, 4 at a time). Broken = an
error with no jobs, or 3 empty runs in a row after it had found jobs. Marks only.

**B3. Database backups.** Job-Ops makes scheduled backups. We have none, and losing the DB means
losing the applied history, outcomes and answer bank. Use the stdlib `sqlite3` backup API once a day
and keep 7 copies in the data dir. About 1 hour.
**Done 2026-11-20** (`core/backup.py`, `test_backup.py`): database only, daily while the app is
open (also at start when due), newest 7 kept, `backup.folder` setting (empty = `<data dir>/backups`),
Settings > Advanced > Backups (newest copy, Back up now), `linkit backup` / `linkit restore FILE`
(checks the file, asks, saves the current database as `linkit-before-restore-*` first).

**B4. Hiring Cafe source.** A large aggregator of ATS jobs. Job-Ops drives it in a browser because
of Cloudflare checks. Under our rules a check stops the source (never solved). Try it on an app-browser
profile like the `google` one. About 1 day; it may be blocked often.

**B4 alternative tested 2026-11-21: plain HTTP, after github.com/umur957/hiring-cafe-job-scraper (MIT).**
That repo POSTs a `searchState` JSON to `hiring.cafe/api/search-jobs` with Chrome-like headers.
**Its exact method is dead:** the site moved to `hiringcafe.com` (308), `get-total-count` is 404,
`search-jobs` answers 405, and the site's own code now sends every non-GET call through
`/api/cloudflare-check` (Turnstile). The same idea still works over GET, with our normal client
(own User-Agent, no faked headers):

- `GET https://hiringcafe.com/?searchState=<json>&page=N` is server-rendered; `__NEXT_DATA__`
  `props.pageProps.ssrHits` holds ~100 jobs (1.2 MB), with `ssrTotalCount` and `ssrIsLastPage`.
  `searchQuery` filters; `locations` takes a place object (name, ISO2, lat/lon), else the IP's country.
- Each hit: `apply_url` straight to the employer ATS (Ashby, Workable, Workday, SmartRecruiters...),
  `v5_processed_job_data` with `company_name`, `formatted_workplace_location`, `workplace_type`,
  `seniority_level`, yearly/monthly pay + currency, `estimated_publish_date`, `requirements_summary`,
  `role_activities`, `technical_tools` (~400 characters together).
- Full description: `GET /api/job-description?id=<objectID>`, one request per job.
- robots.txt does not disallow `/` or `/api/job-description` (only apply clicks, sponsored, org pages);
  the terms page as served says nothing on automated access.
- **Rate limit:** a Cloudflare challenge (403, `cf-mitigated: challenge`) after ~7-8 page loads in about
  a minute (one every 8 s: 7 pages, 697 jobs, then blocked). It lifted within about a minute.

| | HTTP + page data (this) | Browser on an app profile (B4 as planned) |
|---|---|---|
| Works today | yes, tested | not tested; same host, same rate limit and Turnstile |
| Cost per run | a few MB, no browser, runs with the other sources | Chrome per run, slower, one window busy |
| Data | structured: pay, work mode, seniority, place, date, ATS apply link | the same page data, read through a browser |
| Rules (§5.2) | GET only, honest UA, robots respected, a challenge stops the source | same stop on challenge |
| Description | ~400-char summary free; full text costs 1 request per job | same |
| Breakage risk | internal page data, changed once in 14 months | a page redesign breaks it as easily |
| Volume | ~100 jobs per request, paced: ~200 per minute at most | lower |

**How it would work here:** an opt-in aggregator plugin (`sources/aggregators/hiringcafe.py`), one task
per query and place (place object from `geo` coordinates), one page per ~30 s with a checkpoint per page;
a challenge raises the careers-style "bot challenge, not bypassed" error, the source stops for the run
and resumes from its checkpoint next run. Stub `url` = the ATS `apply_url`, so the Deduper merges it
with the same job from an ATS plugin (and `route_ats` picks the handler); priority after the ATS APIs.
Pay, work mode and seniority fill the job's fields, so the hard rules work without the A3 AI step.
Description = the summary lines (no per-job request), as chosen for Gradcracker and Jobindex.
About half a day with a fixture and tests. Recommendation: build this instead of the browser plan.
**Built, measured, then removed 2026-11-21 (maintainer):** live, HiringCafe allowed only 3-7 page
loads per IP before a challenge (240 jobs after a 20-minute quiet gap at one page per 30 s), so
~200-700 jobs per run: unrealistic for this app. B4 is dropped; the findings above stay for reference.

### C. Small UX items

- **C1. More post-apply stages.** Theirs: recruiter screen, assessment, technical, final round, offer.
  Ours: `no_reply, rejected, interview, offer, hired, declined`. Changing the list needs a CLAUDE.md §4 edit.
- **C2. Ctrl+K quick jump** to any job by title or company, with `@state` to filter. We have no global shortcuts.
  **Done 2026-11-20** (`components/quick-jump.ts`): Ctrl/Cmd+K or the top-bar Search button; jobs
  (applied ones too, never the trash; `/api/jobs?applied=true&limit=8`) and app pages; `@strong
  @possible @weak @needs @applied @failed @skipped`, Arabic words too (`@قوي`...).
- **C3. Missing niche sources:** Gradcracker (UK graduates), Jobindex (Denmark), Naukri (India).
  Skip UKVisaJobs: it needs an account login.
  **Done 2026-11-20:** `boards/gradcracker.py` (discipline listings from your titles, card text,
  honeypot card skipped), `boards/jobindex.py` (the page's `Stash` data, card text, employer form
  as apply URL), Naukri via python-jobspy (`regional`; its own API asks for a reCAPTCHA). Country
  presets suggest them for the UK, Denmark and India. Naukri is applied by the agent like any site.

## Not borrowing (and why)

| Job-Ops feature | Why not |
|---|---|
| Tracer links (redirect links in the CV) | needs a public server; redirects look like phishing |
| Gmail AI "smart router" | maintainer chose rules-only reply matching, no AI on mail |
| Ghostwriter chat per job | we write answers automatically; a chat drawer does not serve auto-apply. **Small piece borrowed 2026-11-21:** "Rewrite with AI" / "Draft with AI" in Needs you (free-text answers and the email body, optional wish, Undo; never sensitive) |
| Resume Studio / Reactive Resume | full section rewrites; our patch tailoring is stricter |
| Stale-PDF fingerprint and regeneration | we tailor right before applying. **Small piece borrowed 2026-11-21:** each tailored CV keeps a SHA-256 of its base CV (`tailored_cvs.base_sha`); a retry after a new CV tailors again |
| Map search through OpenStreetMap services | sends the user's location to a third party; A1 does it offline |
| Multi-tenant, SSO, billing, hosted quotas | single-user local app |
| OJCP MCP endpoint | unauthenticated public endpoint, not our goal |
| Umami analytics | breaks "no telemetry". **Instead 2026-11-21:** "Report a problem" / "Suggest a feature" in the footer and "Report this" on runs stopped for an unknown reason open a pre-filled GitHub issue (version, OS, Python, mode, AI, UI language, error code; nothing personal, nothing sent until you submit) |
| Response rate by source | we already have it (`reports._calibration`, `by_source`) |
| "Previously applied" fuzzy warning | covered by dedupe + one application per company. **Small piece borrowed 2026-11-21:** "You applied to <company> before" on the job page and in Add-a-job results (applied jobs, one-per-company name rule) |

## Suggested order

1. A1 location fix (steps 1-2) with tests for the 6 strings above.
2. A4 prose guard.
3. A2 add one job.
4. A3 evidence-checked facts.
5. B3 backups, B2 source health.
6. B1 after the maintainer decides on the refresh.
