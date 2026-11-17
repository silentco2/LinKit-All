# Plan: borrow from career-ops (phase 14)

## Context

career-ops (github.com/career-ops-hq/career-ops, MIT, commit `4e274c2`) is a draft-only job evaluator.
It never submits, but it has field-tested form-safety rules, zero-AI filters, an after-apply loop,
about 55 job sources we lack and a seed list of about 300 employer boards.
LinKit All auto-applies, so every wasted or broken submission costs the user a real application.
This plan ports the parts that serve our goal (CLAUDE.md §1) and leaves the rest out.

Reference clone (read-only): `C:\Users\Osama\AppData\Local\Temp\claude\8ba4113d50cb2051\daaf6f92-42f2-43df-a32d-f3f8f510bd1a\scratchpad\career-ops\repo`.
If it is gone, clone again at commit `4e274c2`. Their code is JavaScript: everything here is a
Python reimplementation, never a copy.

Maintainer decisions already made (2026-11-14):
- Outcomes live in a separate field. `applied` stays the final state.
- Follow-up emails are sent automatically (live mode, follows `submit_without_asking`).
- Inbox reply matching is included, opt-in, rules only, no AI.
- All missing sources are added, in batches.

## End product

```
Sources ──► Discover ──► Enrich ──► Filter/Rank ──► AI Score ──► Tailor ──► Apply ──► Report
 +55 plugins   +300 seed     +generic    +years gate     +requirement   +fact      +knock-out   +outcomes
 (E1-E5)       boards (F1)   liveness    +dealbreakers    importance    check      pre-scan     +calibration
               +name→board   (A6)        (B1, B2)        +confidence    on final   +required    +patterns
               resolver (F2)                              (B3, B4)      CV (D1)    sweep loop   (C1, C4)
               +dead-board                                                         +host        
               rule (F3)                                                           re-detect    
                                                                                   +quirks      
                                                                                   (A1-A5)      
                                    after `applied`:
        inbox reply matcher (C2, opt-in) ──► outcome on the job ──► follow-up email (C3) ──► reports (C4)
        tuning tools: filter audit, coverage check (C5) · safety: SSRF guard (D2), outbound secret guard (D3), golden score set (D4)
```

What the user sees when all of it is done:
1. A job whose form asks a disqualifying question stops in Needs you ("This form would reject you: …") instead of being submitted.
2. Jobs asking for more years than the user has are labelled or dropped before any AI call.
3. Each scored job shows which requirements are must-haves and how sure the score is.
4. Each applied job shows an outcome (no reply, rejected, interview, offer). Home shows whether high scores convert.
5. Email applications with no reply get one automatic follow-up.
6. The Sources list has about 55 new entries and a "Suggested companies" list of about 300 boards.

## Rules for every work package

- CLAUDE.md §2 hard constraints hold. Sensitive questions never go to the AI. Dry run never submits.
- **Never edit CLAUDE.md** (it is at 199 of 200 lines). The maintainer decides the lines listed in "CLAUDE.md decisions" below.
- One module per package where possible. Type hints, ruff and mypy clean, a test for every new logic path.
- New source = plugin + fixture under `tests/fixtures/<name>/` + test. No live-site calls in CI.
  Fixtures are captured once by hand from the public endpoint and trimmed to 2-3 postings with made-up names.
- Every ported file's docstring ends with `Logic adapted from career-ops (MIT).` and NOTICE gets one entry (step 0).
- User-facing words go through `frontend/src/app/i18n/en.ts` and `ar.ts`.
- Each package ends with: `uv run ruff check . && uv run mypy src && uv run pytest tests/unit -q`.

## Step 0: setup (do first, 15 minutes)

- Copy this plan to `docs/career-ops-borrow-plan.md` so later agents can verify against it.
- NOTICE: add career-ops (MIT, Santiago Fernández de Valderrama) and its `employers/` data (CC BY 4.0).
- Done when: both files exist and `git diff --stat` shows only those two.

## A. Apply reliability

| ID | What | Where | Done when |
|---|---|---|---|
| A1 | **Knock-out pre-scan.** Before answering, compare form questions with the profile by rules only: minimum years, required degree, sponsorship / work authorization, salary floor. A mismatch parks the job with code `knockout`, the question text and the profile value. Buttons: "Apply anyway", "Skip". Runs in dry run too. | new `apply/knockout.py` (pure functions on `Question` + `Context`); called in `apply/agent/__init__.py:step` and `handlers/base.py` before `answer_questions`; park via `runner._park`; card in `frontend/.../needs-you` | `tests/unit/test_knockout.py`: years, degree, sponsorship and salary each park; a matching profile does not; `tests/e2e` dry-run fixture form with "at least 8 years" parks `knockout` |
| A2 | **Required-field sweep until stable.** After filling, re-snapshot and repeat while new required controls appear (max 4 passes). Read state, not value: checkbox `checked`, radio group has a checked member, select is not on its placeholder. | `apply/agent/__init__.py:step` (the `after = snapshot(page)` block), `apply/agent/snapshot.js` and its mirror `extension/snapshot.js`, reuse `form.lost_values` | `tests/unit/test_required_sweep.py` with an HTML fixture where "Yes" reveals a required follow-up: the follow-up is listed, not missed |
| A3 | **Re-detect the ATS after the Apply click.** After each hop, run `sources/ats_detector` on the final URL, store it as `job.data["apply_host"]`, and choose tactics from that host. | `runner._agent_apply`, `runner._hand_to_handler` | unit test: board URL on Phenom, form URL on `myworkdayjobs.com` → Workday tactics chosen, event `apply_host_changed` written |
| A4 | **ATS quirk table.** One data file of per-host rules read by the filler: Workday = type real keystrokes + type-ahead in drop-downs, never positional clicks; repeated "Add another" blocks = locate per block; Lever = never script-click checkboxes or radios (list them for the user); Ashby = second application to the same company warns about email merge. | new `apply/quirks.py` (dict host → flags), read in `apply/form.py:fill`, `_choose`, `_combobox` | `tests/unit/test_quirks.py`: each host returns its flags; Workday fixture fills by typing; Lever fixture leaves checkboxes untouched and reports them |
| A5 | **Stored-profile reminder.** After a submission on SuccessFactors-family hosts, the applied event carries code `check_stored_profile`. | `runner._fill_and_decide`, i18n | unit test asserts the code on a SuccessFactors host only |
| A6 | **Generic closed-posting detection.** Text patterns for "no longer accepting", "position has been filled" and equivalents (EN, AR, FR, DE, ES), normalised for typographic quotes and accents. Workday `/apply` 404: retry without `/apply` and query string before calling it closed. | new `sources/liveness.py`; used by `agent._dead_end`, `agent._closed_badge`, `Source.is_live` default in `sources/base.py` | `tests/unit/test_liveness_text.py`: 12 closed phrasings match, "application form has been filled out" does not |

## B. Filtering and scoring

| ID | What | Where | Done when |
|---|---|---|---|
| B1 | **Years of experience from the JD body.** Rules only. New filter `filters.max_years_required` (default off) with `years_action: "label" | "drop"`. Drop only when the JD states a clear overall requirement and its lowest reading is above the user's years. Preferred-only or per-skill figures never drop. | new `matching/years.py`; call in `matching/rules.py:rule_violation`; field in `core/search.py:FiltersSection`; label in `job.data["years_required"]`; Settings → Jobs & places | `tests/unit/test_years.py`: "5+ years" → 5, "3-5 years" → 3, "10 years of Java preferred" → none, Arabic "خبرة 5 سنوات" → 5 |
| B2 | **Dealbreakers.** `filters.dealbreakers: list[str]`. A job is filtered out only when a JD sentence contains the phrase; the sentence is stored as the reason. | `core/search.py`, `matching/rules.py`, Settings | unit test: phrase present → filtered with quoted sentence; absent → passes |
| B3 | **Requirement importance.** Score output gains `requirements: [{text, importance: critical|high|meaningful|preferred, basis: stated|structural|inferred, met: yes|partial|no}]`, max 8 per job. The prompt lists requirements from the JD before reading the CV. Code rejects `inferred` + `critical|high` (downgrades to `meaningful`). The 1-10 score rule is unchanged. | `providers/prompts/score.j2`, schema in `matching/score.py`, Jobs page detail | `tests/unit/test_score_requirements.py`: downgrade rule; old cached responses without the field still parse |
| B4 | **Score confidence.** `job.data["confidence"]`: `low` when the description is under 400 characters or was cut, or the AI marks CV evidence missing; else `medium` / `high`. Shown beside the score. Never changes the tier. | `matching/score.py`, Jobs page | unit test for the three levels |
| B5 | **Deadline priority.** Extract a closing date from the JD ("closes", "deadline", "apply by"); jobs closing within 3 days sort first in `Applier.pick_jobs`. | new `matching/deadline.py`, `runner.pick_jobs` | `tests/unit/test_deadline.py` |

## C. After applying

| ID | What | Where | Done when |
|---|---|---|---|
| C1 | **Outcome field.** `jobs.outcome` (`no_reply`, `rejected`, `interview`, `offer`, `hired`, `declined`) + `outcome_at`. Each change adds a `JobEvent` with code `outcome` (state stays `applied`). API `POST /api/jobs/{id}/outcome`; Jobs page selector. | `core/models.py`, Alembic migration, `api/routes.py`, frontend `types.ts` | migration up/down test; API test; state machine test proves `applied` is still terminal |
| C2 | **Inbox reply matcher** (opt-in `email.read_replies`, default off). Reads mail since the first application, matches sender domain and company name (word-boundary for short names) and role, classifies rejection / interview invite / other by phrase lists, sets the outcome. Rules only: mail text never reaches the AI or the log. Unmatched mail is ignored. | new `apply/replies.py`; reuse `email_verify._imap_rows`, `email_verify.microsoft`, `email_verify.credentials`; scheduled with APScheduler after each run | `tests/unit/test_replies.py` with 10 fixture mails: correct job and class; "HP" does not match "PHP"; nothing logged |
| C3 | **Automatic follow-up.** For jobs applied by email, live mode only: one follow-up after `apply.followup_days` (default 7) with no reply, sent when `submit_without_asking` is on, else parked `confirm_email`. Counts in `email_daily_cap`. One per job, ever. Body from the model (CV/profile only, English), greeting and signature in code. | `apply/email_apply.py`, new prompt `followup_email.j2`, `core/search.py:ApplySection` | unit tests: not before day 7; not after a reply; never twice; dry run writes an .eml only |
| C4 | **Calibration and patterns.** Report adds: conversion (interview or better) per score band with a minimum of 5 per band, and per ATS / per source. Advisory only: never changes thresholds. | `reports/__init__.py:build_report`, Home charts | `tests/unit/test_calibration.py`: bands under 5 show "not enough data" |
| C5 | **Tuning tools.** `linkit filter-audit`: per title include / exclude word, how many jobs it decided and their average score. `linkit why-missed <url>`: says which filter, source gap or dedupe hid a posting. Both read-only. | `cli.py`, new `matching/audit.py` | CLI tests on a seeded DB |

## D. Trust and safety

| ID | What | Where | Done when |
|---|---|---|---|
| D1 | **Fact check on the final CV.** After rendering, extract text from the tailored PDF and compare with the original: every number, date, employer and job title in the tailored text must exist in the original or the locked facts. A new one rolls the patches back (event `tailor_fact_check_failed`). | new `tailor/verify/facts.py`, called in `tailor/pipeline.py` next to `verify_pdf` | `tests/unit/test_tailor_facts.py`: "Engineer" → "Senior Engineer" fails; "40%" not in source fails; reworded bullet passes |
| D2 | **SSRF guard.** Before any fetch of a user-pasted or scraped URL, resolve the host and refuse loopback, link-local, RFC1918 and cloud-metadata addresses. `localhost` stays allowed for our own API. | `sources/http.py` | unit test with a patched resolver |
| D3 | **Outbound secret guard.** One check in `LLMProvider.complete`: the prompt must not contain a vault password, token or app password (reuse `apply/answers.py:scrub` and `remember_secrets`). A hit raises and is logged without the value. First read `providers/base.py`; if the check already exists there, only add the test. | `providers/base.py` | `tests/unit/test_providers.py`: prompt with a remembered secret is refused |
| D4 | **Golden score set.** 20 made-up job + CV pairs with an expected tier, run through `linkit bench` with a recorded provider response; fails when a prompt change moves more than 2 of 20. | `bench/ai.py`, `tests/fixtures/golden/` | `uv run pytest tests/unit/test_golden_scores.py` |

## E. Job sources (55 plugins)

Pattern for each: read their `providers/<name>.mjs` and `tests/providers/<name>.test.mjs` for the endpoint and field mapping, write a `Source` subclass like `sources/aggregators/remotive.py` (feed) or `sources/ats/pinpoint.py` (per-tenant), add the fixture and a test in `tests/unit/test_sources.py` style, register the label in `sources/labels.py` and the host in `sources/ats_detector.py`.
First check each name against our plugins by host: `platsbanken` = our `jobtech`, `ultipro` = `ukg`, `adp-workforcenow` = `adp` are already covered and are skipped.

| Batch | Plugins | Folder |
|---|---|---|
| E1 ATS (18) | applicantpro, clearcompany, collage, darwinbox, eightfold, flowxtra, hirehive, homerun, inrecruiting, joinup, magneto, neogov, polymer, prevueaps, redrover, rexx, talentlink, turbohire | `sources/ats/` |
| E2 global boards (9) | 4dayweek, agentic-jobs, echojobs, generalist-world, startup-jobs, larajobs, higheredjobs, consider (VC portfolio boards), techinasia | `sources/boards/` or `aggregators/` |
| E3 regional boards (17) | bulldogjob, justjoin (PL); jobscz, pracecz (CZ); germantechjobs (DE); vdab (BE); tes (UK); jobbankca (CA); computrabajo, occ (LatAm); careerviet, topdev (VN); glints, jobstreet (SE Asia); yourator (TW); senjob (SN); interamt (IT) | `sources/aggregators/` |
| E4 company pages (7) | aldi-nord, atlassian, bwi, deutschebahn, hecklerkoch, rheinmetall, tkms | `sources/companies/` |
| E5 generic (4) | sitemap (jobs from a site's sitemap.xml), wp-job-manager, notion (public Notion job pages), feishu-jobs | `sources/ats/` |

Done when, per batch: every listed name appears in `registry()`, has `tests/fixtures/<name>/`, a passing parse test, a label, and `tests/unit/test_registry_keys.py` passes. All new sources are opt-in (`sources.enabled`), as today.

## F. Companies and upkeep

| ID | What | Where | Done when |
|---|---|---|---|
| F1 | **Seed boards.** Convert their `templates/portals.example.yml` (261 companies, MIT) and `employers/boards/**/*.ndjson` (about 53 rows, CC BY 4.0) into `src/linkit_all/data/company_boards.json` (`{ats, slug, name}`), deduped, only ATSs we have a plugin for. `linkit seed-boards` loads them through `discovery.upsert_boards(..., source="career-ops")`. Settings → Sources shows them as "Suggested companies" to tick; nothing is crawled until ticked or `use_discovered_boards` is on. | one-off `scripts/build_company_boards.py`, `sources/discovery.py`, `cli.py`, `api/suggest.py`, Sources settings page | JSON has ≥ 280 rows, no duplicates; `linkit seed-boards` twice inserts 0 the second time; API test for suggestions |
| F2 | **Company name → board resolver.** `linkit find-board "Stripe"` probes the public APIs of our ATS plugins with slug guesses and prints the boards that exist and list ≥ 1 job. Preview by default, `--add` saves to `sources.companies`. Also behind the Sources "Add company" box. | new `sources/resolve.py` reusing each `Source.is_known` / `search`; `cli.py`; `api/routes.py` | unit test with mocked HTTP: found on Greenhouse, not found → listed for manual follow-up |
| F3 | **Dead-board rule.** In `discovery.note_crawl`, only a real HTTP 404 / 410 advances the failure counter; throttles, timeouts and DNS errors do not. | `sources/discovery.py` | unit test: five 429s leave the board on, five 404s switch it off |
| F4 | **Repost guard.** In the ghost score, a repeat sighting counts as a repost only with a different URL on a different scan date within 90 days; two open requisitions with different ATS ids on the same day do not. | `matching/trust/ghost.py`, `core/sightings.py` | unit test for sibling requisitions vs repost |

## Not borrowed

Prompt-file architecture, markdown as database, the Go dashboard, interview / negotiation / offer-contract modes, country legal checks, contact discovery and LinkedIn outreach, CV templates, `robots-check`, `local-parser`.

## CLAUDE.md decisions for the maintainer (agents do not edit the file)

1. §5.5 email: a follow-up is a second mail to the same address (today: "never the same address twice").
2. §5.7: new parked reason `knockout`.
3. §5.3: years gate and dealbreakers as hard rules 1.
4. §6: opt-in inbox reading for reply matching.
5. §4: `jobs.outcome` beside the state machine.
6. §10: phase 14 line.

## Order and size

Step 0 → A1, A2 (highest value) → B1, B2 → D1 → C1 → C2, C3, C4 → A3-A6 → B3-B5 → D2-D4 → F1-F4 → E1 → E2 → E3 → E4 → E5 → C5.
Independent groups that can run in parallel sessions: A, B, C (after C1), D, E batches, F. Two writers never touch the same file: `runner.py` and `agent/__init__.py` belong to group A only; `rules.py` and `search.py` to group B (C3 adds its `ApplySection` field after B lands).
Rough size: A 2 days, B 1.5 days, C 2.5 days, D 1.5 days, F 1 day, E about 5 days (55 plugins at 40-60 lines each).

## Verification (for the checking agent)

1. For every ID above, confirm the "Done when" test file exists and passes: `uv run pytest tests/unit -q -k "<name>"`.
2. Whole suite: `uv run ruff check . && uv run mypy src && uv run pytest -q` (e2e is dry-run only).
3. Sources: `uv run python -c "from linkit_all.sources import registry; r=registry(); print(len(r))"` is at least 55 higher than before step 0 (record the before number in `docs/career-ops-borrow-plan.md`). Every E-table name is a key.
4. Companies: `linkit seed-boards` then `linkit status` shows the seeded boards; second run adds none.
5. Apply: `linkit apply-probe` against the bench fake board (`src/linkit_all/bench/board.py`) with a knock-out form parks `knockout`; with a reveal-on-answer form fills the revealed field; nothing is submitted in dry run.
6. UI: start the app with `preview_start`, open Jobs (confidence, requirements, outcome selector), Needs you (knock-out card), Settings → Sources (new plugins, Suggested companies), Home (calibration chart). Check English and Arabic.
7. Constraints: grep new code for model calls on sensitive questions (none), for mail text in logs (none), and confirm `git diff CLAUDE.md` is empty.
8. Tick each ID in `docs/career-ops-borrow-plan.md` with the commit that delivered it. A package without a passing test is not done.

## Status (2026-11-17, nothing committed yet)

Source plugins: **243 before step 0, 295 after** (52 new; group E report).

| ID | Status | Test |
|---|---|---|
| Step 0 | done | NOTICE entry, this file |
| A1 | done | `tests/unit/test_knockout.py`, `test_api.py` (knockout decision), e2e `test_apply_generic.py::test_knockout_question_parks_before_anything_is_filled` |
| A2 | done | `tests/unit/test_required_sweep.py` (fixture `tests/fixtures/agent/reveal_on_answer.html`) |
| A3 | done | e2e `test_apply_generic.py::test_apply_hop_to_another_ats_records_the_form_host` |
| A4 | done, one deviation | `tests/unit/test_quirks.py` |
| A5 | done | e2e `test_apply_generic.py::test_successfactors_submission_asks_to_check_the_stored_profile` |
| A6 | done | `tests/unit/test_liveness_text.py` |
| B1-B5 | done (group B session); B5 sort hooked into `Applier.pick_jobs` | `test_years.py`, `test_score_requirements.py`, `test_deadline.py` and others |
| C1 | done | `tests/unit/test_outcome.py` |
| C2 | done | `tests/unit/test_replies.py` |
| C3 | done, one deviation | `tests/unit/test_followup.py` |
| C4 | done | `tests/unit/test_calibration.py` |
| C5 | done | `tests/unit/test_audit.py` |
| D1-D4 | done (group D session) | `test_tailor_facts.py`, `test_providers.py`, `test_golden_scores.py`, SSRF test |
| E1-E5 | 53 of 55 (group E session) | per-plugin fixtures and tests |
| F1-F4 | done (group F session) | see group F report |

Deviations from the plan, and why:
- **A4 Lever:** the plan said never script-click Lever checkboxes or radios and list them for the user. That would park nearly every Lever form (most have consent or EEO choices). Instead Lever ticks only with real input events and never the page-script click fallback, which is what raises hCaptcha.
- **C3 follow-ups when "submit without asking" is off:** the plan said park `confirm_email`. A follow-up belongs to an `applied` job, and parking would move it out of a final state, which the state machine forbids. The job's history gets a one-time `followup_due` note instead. With the switch on, live mode sends.
- **E:** `applicantpro` is a duplicate of `ats/isolvedhire.py`. `echojobs` is blocked (bot checkpoint and robots `/api` disallow upstream; passing it would break CLAUDE.md §5.2). `interamt` is blocked (stateful search form; the shared page browser can only load an address).
- **Job event codes** added here (`apply_host_changed`, `check_stored_profile`, `email_merge`, `workday_listing`, `outcome`, `followup_*`) show their English message in the UI, like the existing `apply_resolved`.
