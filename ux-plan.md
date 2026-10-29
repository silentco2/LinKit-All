# UX plan and audit: LinKit All before V1

Written 2026-10-29. Status: plan only. None of it is built yet.
Goal: make the app **simple, usable, learnable and memorable**, and get a new user from install to the first
job search with as few inputs as possible, with no invented answers (CLAUDE.md §2 still applies to everything).

Read with `CLAUDE.md` (binding rules), `plan.md` and `handoff.md`. Section 13 lists the CLAUDE.md edits this plan needs.

---

## 0. TL;DR

| | Today | After this plan |
|---|---|---|
| Setup screens | 10 tabs, 2 rows, no Next/Back | 4 short first-run screens; the rest is Settings or asked just in time |
| Controls shown before the first search | ~90, plus ~100 source checkboxes | **5 decisions** (upload CV, pick AI, confirm profile, confirm roles + place, start) |
| Fields asked twice | name, location, country, currency ×3, email, company, title, links | each asked once, or derived |
| Save buttons | ~12 (most of them save *everything*) | 0: autosave with a "Saved" tick |
| Nav items | 8 | 5: Home, Jobs, Needs you, Activity, Settings |
| Starting a run | 5 stage checkboxes + "new vs resume" | 1 smart button whose label follows the state |
| Going live | a checkbox anytime | guided unlock after a reviewed practice run |

The core change is a **rule-based inference layer** (section 4): the CV plus the country plus the target roles
derive nearly every other setting. Each derived value shows where it came from and stays editable.

---

## 1. Decisions taken (maintainer, 2026-10-29)

| # | Topic | Decision |
|---|---|---|
| D1 | Persona | **Both**: tech and non-tech. The track is chosen at the start. The plan *pre-selects* it from the CV, so it costs one tap, not a question |
| D2 | CV parsing | **Rules first, AI fills the gaps.** Each AI-filled value is marked "check this" |
| D3 | Work authorization | **Suggested from the country of residence, one-tap confirm, nothing pre-ticked.** Sponsorship is then worked out per job from the confirmed list |
| D4 | Vault | **Asked only when first needed** (first account sign-up or adding Gmail). There's no vault step in setup |
| D5 | Navigation | **Merge Review + Action Center into "Needs you".** Nav: Home, Jobs, Needs you, Activity, Settings |
| D6 | Terms | **Plain words** (glossary in section 9) |
| D7 | Saving | **Autosave** on blur with a "Saved" tick. Risky switches still confirm |
| D8 | Salary | **One expectation** (used only to answer forms). The filter floor is a separate opt-in, off by default. **One currency**, from the country |
| D9 | Run control | **One smart button** on Home. Resume is automatic; stages move under Advanced |
| D10 | Live mode | **Guided unlock** after the first practice run |
| D11 | Tuning knobs | **Presets** (Pace, Pickiness) **+ a collapsed Advanced section**; changed values are marked |

---

## 2. How this audit was done

- **Code read**: `frontend/src/app/pages/setup.ts` (all 1068 lines), `app.ts`, `app.routes.ts`, the copy in
  `i18n/en.ts`, plus the models in `core/search.py`, `core/profile.py` and `apply/answers.py`.
- **App run** on a fresh data dir (`build/ux-audit/data`), first-run screens: Setup, Jobs, Live run, Action Center.
- **Frameworks used**: design critique (first impression, usability, hierarchy, consistency), UX copy
  (clear, concise, consistent, useful, human), the UI/UX Pro Max rule base (onboarding, forms & feedback,
  navigation: `progressive-disclosure`, `multi-step-progress`, `form-autosave`, `error-recovery`,
  `empty-states`, `nav-hierarchy`, `undo-support`), Nielsen's 10 heuristics, and a user-research
  validation plan (section 14).
- **Out of scope on purpose**: visual polish, colour and contrast, and an accessibility pass. You asked for UX
  first. Those come after V1's flow is settled.

---

## 3. Audit findings

Severity: 🔴 blocks or tires new users · 🟡 slows or confuses · 🟢 polish.

### 3.1 Onboarding

| # | Finding | Sev | Heuristic | Fix (section) |
|---|---|---|---|---|
| O1 | 10 setup tabs in 2 rows, with no Next/Back and no "step x of y". Users can't tell what's required and what's optional | 🔴 | Visibility of status, minimalist design | 4-screen first run (5) |
| O2 | Profile asks for name, email, phone and location **before** the CV upload, then Answers asks first/last name, city, country, company, title, links and years again. All of it is in the CV | 🔴 | Recognition over recall, error prevention | Inference layer (4) |
| O3 | The location is typed 4 times: profile location, search locations, filter locations, Indeed country (`"egypt"` as free text) | 🔴 | Consistency | One "Where" field (4.3) |
| O4 | Currency is typed 3 times: filter currency select, answers currency text, implicit country | 🟡 | Consistency | One currency from the country (D8) |
| O5 | Sources: ~100 checkboxes, **all off**, plus 8 site boxes and Telegram. That's choice overload, and a new user gets nothing they didn't tick | 🔴 | Flexibility vs. minimalism | Presets per track + country (4.4) |
| O6 | Telegram defaults are Russian-language channels (from freehire). They're wrong for MENA users and add noise | 🔴 | Match with the real world | Country/track channel lists (4.4) |
| O7 | Vault, Email and API keys are three main-flow steps, all optional, and two need the vault first. The order makes users solve problems they don't have yet | 🔴 | Minimalism | Just-in-time setup (6) |
| O8 | Step ticks: "Application answers" and "Applying" **never** show ✓ (hard-coded `false`), and "Filters" ticks whenever "Search" does. Setup never feels finished | 🟡 | Visibility of status | Real completion rules (5.5) |
| O9 | The "Setup isn't finished, open the setup wizard" banner shows **on the setup page itself**, and on every page | 🟢 | Aesthetic, minimalist | Replace with a progress chip (5.5) |
| O10 | The finish checklist shows LibreOffice ✗ while the Start button is enabled (`allReady` ignores it) | 🟢 | Consistency | One readiness rule (5.5) |
| O11 | The first visit lands on **Jobs** (empty), not setup (`'' → jobs`) | 🟡 | Help users start | `''` → Home, which routes a new user to the first run (7) |
| O12 | AI step: "Test" and "Save" are separate, and the model field is free text. The app already detects installed CLIs (`available`) but doesn't pre-select or auto-test | 🟡 | Error prevention | Auto-detect + test on pick (5.2) |
| O13 | 24 answer fields in one form (13 basics, 4 sensitive, 5 EEO, 2 agreements) | 🔴 | Minimalism | 4 derived, 3 one-tap, the rest just in time (4, 6) |

### 3.2 Saving and feedback

| # | Finding | Sev | Fix |
|---|---|---|---|
| F1 | Search, Filters, Scoring, Trust, LinkedIn, Apply and Email cap each have a Save button, but all of them `PUT` the **whole** config. "Filters saved" also silently saves Apply edits made on another tab. The mental model is wrong | 🔴 | Autosave per field (D7) |
| F2 | Unsaved edits are lost when you leave the page, with no warning (`form-autosave`) | 🟡 | Autosave |
| F3 | Server errors are shown raw (`(e as Error).message`) in a banner at the top, far from the field (`error-placement`, `error-clarity`) | 🟡 | Inline error under the field: cause + fix |
| F4 | One shared message banner per page: a success on one card shows above an unrelated card | 🟢 | Per-field "Saved" tick |

### 3.3 Information architecture

| # | Finding | Sev | Fix |
|---|---|---|---|
| I1 | 8 flat nav items. Answer bank and Vault are settings, not daily places; Review and Action Center are both "things waiting for me" | 🟡 | 5 items (7) |
| I2 | Two places for answers (Setup → Answers, Answer bank) and two for the vault (Setup → Vault, Vault page) | 🟡 | One home each, under Settings |
| I3 | Live run mixes run control, Schedule, Activity and the screenshot view; Report is a separate page about the same runs | 🟡 | "Activity" = live now + history + report |
| I4 | No "home": nothing answers "what should I do now?" | 🔴 | Home with the next best action (7.1) |
| I5 | Schedule is hidden inside Live run | 🟡 | A one-line toggle on Home: "Search every day at 09:00" |

### 3.4 Running and applying

| # | Finding | Sev | Fix |
|---|---|---|---|
| R1 | 5 stage checkboxes (Find jobs, Read descriptions, Filter & rank, AI scoring, Apply) expose the pipeline instead of the user's goal | 🟡 | Smart button (8.1) |
| R2 | "Start a new run (otherwise an unfinished run resumes)" asks users to reason about run internals | 🟡 | Auto-resume; "Start fresh" sits in Advanced |
| R3 | Live mode is one checkbox, with nothing proving that practice mode worked | 🔴 | Guided unlock (8.2) |
| R4 | Live run's Start is enabled while setup is unfinished | 🟢 | The button explains what's missing |

### 3.5 Review and Action Center

| # | Finding | Sev | Fix |
|---|---|---|---|
| A1 | Parked applications are one card each. If 9 jobs ask "notice period", the user answers 9 times (the answer bank helps only *after* the first one) | 🔴 | Batch-resolve by question (10) |
| A2 | Review has bulk approve but no undo (`undo-support`) | 🟡 | 10 s "Undo" toast |
| A3 | No keyboard flow for reviewing many jobs | 🟢 | J/K move, A approve, S skip, O open |
| A4 | A filtered or low job doesn't say *why* in plain words at list level | 🟡 | One-line reason chip ("Title has 'intern'", "Scam score 72") |

### 3.6 Copy and terms

| # | Finding | Sev | Fix |
|---|---|---|---|
| C1 | Mixed vocabulary: dry run, tiers high/mid/low, run, stage, Action Center, vault | 🟡 | Glossary (9) |
| C2 | Implementation details in hints: "Wuzzuf … 1 page per 10 s", "`LINKIT_API_KEY`", "One AI call per form page", "Indeed only (Glassdoor gets none)" | 🟡 | Move them to Advanced or the docs |
| C3 | The "/" split syntax for searches is only explained in a hint | 🟢 | Show the split as chips while typing |
| C4 | CV intro is 4 sentences about formats before the button | 🟢 | "Upload your CV (Word, PDF, ODT or LaTeX)" + a "Which format is best?" link |

### 3.7 What already works well (keep)

- Privacy promise up front ("Everything stays on this computer…"). It's the right first message.
- "Ask me" as the explicit default for sensitive answers is clear and honest. Keep the term.
- The PDF → DOCX approval gate and the CV segment preview build trust.
- Live badges for review and actions counts, desktop notifications, EN/AR with RTL.
- Plain, friendly copy in most hints. The tone is already good; it's the *amount* of copy that's the problem.

---

## 4. The inference layer (rule-based, no invented answers)

### 4.1 Confirmation levels

Every setting falls into one of three levels. The UI shows a small source badge on each value: **From your CV ·
From your country · From your roles · You set this**.

| Level | Meaning | UI |
|---|---|---|
| **Auto** | Derived by a rule, low risk, shown and editable | Filled in, with a source badge |
| **Suggest** | Derived, but the user must tap to accept (sensitive, or a guess with real consequences) | Shown as a question with the suggestion as a button; nothing is used until tapped |
| **Ask** | Never derived (§2) | Left on "Ask me"; asked just in time (section 6) |

AI-filled CV values (D2) are always **Auto + "check this"** until the user has looked at the confirm screen once.

### 4.2 Field map: what derives what

Inputs the user actually gives: **CV file, AI choice, target roles (confirm), where (confirm), track (confirm)**.

| Setting today | Derived from | Rule | Level |
|---|---|---|---|
| `full_name` | CV | First non-empty paragraph above the contact line, or the largest font run on page 1 | Auto |
| `email`, `phone` | CV | Regex; DOCX hyperlinks (`mailto:`/`tel:`) are read from the rels too; phone normalized with the country code | Auto |
| `location` | CV | Header line next to the contacts matching "City, Country" against a city/country list (EN + AR names) | Auto |
| `first_name`, `last_name` | full name | First token / last token. Arabic particles join the next token: *Abd, Abdel, Abdul, Abu, El, Al, Bin, Ibn* ("Abdel Rahman") | Auto |
| `city`, `country` | location | Split on the comma, checked against the country list | Auto |
| `linkedin`, `github`, `portfolio` | CV | URL regex + DOCX hyperlink targets, by domain | Auto |
| `current_company`, `current_title` | CV | The experience entry whose date range ends in *Present / Current / Now / حتى الآن / الآن* | Auto |
| `years_experience` | CV | Union of non-overlapping experience date ranges (internships count half or are excluded; see Q2 in section 15) | Auto |
| `locked_facts` | CV | Every employer, title, degree and institution found → pre-listed as "Never changed" (numbers, dates and contacts are already auto-locked) | Auto |
| `skills` | CV | The "Skills" section split on `, • | ;` + a known-skills lexicon matched anywhere in the CV | Auto |
| **track** (new) | skills + titles | ≥ 3 lexicon tech skills **or** a tech title word (engineer, developer, data, devops, QA…) → *Tech*, else *General* | Suggest (one tap: "Looks like tech jobs · Change") |
| `search.queries` | CV titles | Current + past titles, normalized, seniority words removed, deduped, max 5 → chips the user taps on/off | Suggest |
| `search.locations` + `filters.locations` | location + remote | **One field: "Where".** Defaults to the city's country + "Remote" if remote is on. Both config lists are written from it | Auto |
| `filters.work_modes` | — | Default all three; "Include remote jobs" toggle on the roles screen | Auto |
| `filters.seniority` | years + title words | Band ±1: 0–1 y intern/junior · 1–3 junior/mid · 3–6 mid/senior · 6–10 senior/lead · 10+ lead/manager/executive. *Senior/Lead/Head/Manager* in the current title raises the band | Auto |
| `filters.title_exclude` | seniority band | Words two or more bands away (mid → *intern, director, VP, head of*) | Auto (Advanced) |
| `filters.title_include` | — | Empty (ranking already handles relevance); Advanced only | — |
| `sources.jobspy_country` | country | Country name → the jobspy key (`Egypt → egypt`) | Auto |
| `sources.regional`, `sources.enabled`, `sources.jobspy` | country + track | Preset table (4.4) | Auto |
| `sources.telegram_channels` | country + language + track | Curated list per region (4.4); empty when there's no list | Auto |
| `sources.linkedin_keywords` | queries + language | `"<query> hiring"` + Arabic `"مطلوب <query>"` when the CV or UI is Arabic | Auto (the feature itself stays opt-in) |
| `filters.salary_currency`, `answers.salary_currency` | country | One currency per country (EGP, SAR, AED…) | Auto |
| `email.imap_user` | profile email | Same address; no field | Auto |
| `email.imap_host`, `smtp_host`, `smtp_port` | email domain | gmail/googlemail → Google; yahoo.* → Yahoo; outlook/hotmail/live → "not supported yet" message *before* the user hunts for an app password | Auto |
| `answers.heard_about` | the job's source | Per job: "LinkedIn", "Wuzzuf", "Company website"… (`Context.job_source` already exists) | Auto (field removed from setup) |
| `answers.willing_to_relocate` | "Where" vs residence | "Where" includes a place outside the home country → suggest **Yes**; only home + remote → don't ask | Suggest |
| `answers.authorized_countries` | country of residence | "Are you authorized to work in **Egypt**?" Yes / No, nothing pre-ticked (D3) | Suggest |
| `answers.needs_sponsorship` | authorized list + **job country** | Per job: job country in the list → "No"; not in the list → "Yes"; country unknown → park (Ask) | Rule from profile data, per job |
| `answers.salary_expectation` | — | Asked once, optional; "Ask me" by default (§2) | Ask |
| EEO ×5 | — | One row: **Prefer not to say for all / Ask me each time / Answer now** (expands the 5 selects) | Ask (one control) |
| `acknowledge_privacy`, `acknowledge_legal` | — | Just in time, with "Always accept privacy notices" on the first card (section 6) | Ask |
| `notice_period` | — | Just in time, a select (Immediately / 2 weeks / 1 month / 2 months / 3 months), saved to the profile | Ask |
| AI provider | PATH scan | One CLI found and signed in → pre-selected and auto-tested; several → the CLI first, then API key, then local | Auto |
| Tiers, AI max, batch | Pickiness preset | Strict 9/6 · Balanced 8/5 · Wide 7/4 (`tier_high`/`tier_mid`) | Auto |
| Apply pace/caps/parallel | Pace preset | Careful (1 site, 60–120 s, 10/day) · Balanced (current defaults) · Fast (3 sites, 20–60 s, 20/day) | Auto |

Implementation home: a new `core/infer.py` (pure functions: `infer(cv_segments, profile, country) -> Inferred`,
each value carries `source` and `level`) plus `core/presets.py` (country/track tables as data). It's unit-tested
with CV fixtures in EN and AR. The UI never invents; it only renders `Inferred`.

### 4.3 One "Where" concept

Users think "where do I want to work", not "search locations vs. filter locations vs. Indeed country". The roles
screen has one chip input, **Where**, prefilled from the CV country, plus an **Include remote jobs** toggle. The
backend writes `search.locations`, `filters.locations`, `jobspy_country` and the region presets from it. The raw
lists stay in Advanced for power users.

### 4.4 Preset tables (data, not code)

| Region | Regional boards | jobspy | Currency | Telegram |
|---|---|---|---|---|
| Egypt | Wuzzuf, Forasna, Bayt | LinkedIn, Indeed, Google | EGP | Egyptian job channels (**to curate**, see section 15) |
| Gulf (SA, AE, QA, KW, BH, OM) | Bayt (Naukrigulf when unblocked) | LinkedIn, Indeed, Google, Glassdoor | local | Gulf channels (to curate) |
| Other | — | LinkedIn, Indeed, Google, Glassdoor | local | none |

| Track | Extra sources on |
|---|---|
| Tech | ATS feeds (Greenhouse/Lever/Ashby…), remote-job aggregators, tech boards |
| General | Regional boards only + aggregators that aren't tech-only |

Everything stays editable in **Settings → Sources**. The 100-row list stays, but with the preset ticked, a
"Recommended for you" filter, and the region/track shown on each row.

---

## 5. New first run: 4 screens

Progress: "Step 2 of 4" with Back on every screen; Skip where optional (`multi-step-progress`, user freedom).

### 5.1 Screen 1: Welcome + CV

```
LinKit All finds jobs, tailors your CV and applies for you. Everything stays on this computer.
[ English | العربية ]

   ┌───────────────────────────────────────────┐
   │   Drop your CV here, or Choose a file     │
   │   Word, PDF, ODT or LaTeX                 │
   └───────────────────────────────────────────┘
   Which format works best?  (link → docs)
```
- Rules extraction runs on upload (instant). The PDF conversion approval stays as it is, shown here.
- LibreOffice missing → inline "Install LibreOffice (439 MB)" with the existing `linkit install-libreoffice`
  path, not just "run linkit doctor".

### 5.2 Screen 2: Connect your AI

- Detected CLIs show a "Found on this computer" badge. One is pre-selected and **auto-tested** on screen open.
- Picking a card tests it right away; success saves it. There's no separate Test/Save.
- Model is an optional dropdown of known models, not free text (free text stays in Advanced).
- After success, the AI fills the CV fields the rules missed (D2), in the background.

### 5.3 Screen 3: Check what we found

One card, grouped, every value with a source badge, edit in place:

```
You                      Sara Ahmed · sara@… · +20 …      From your CV
                         Cairo, Egypt                           From your CV
Now                      Backend Engineer at Acme · 5 years     From your CV  ⚠ check this
Links                    linkedin.com/in/… · github.com/…       From your CV
Skills (14)              Python, FastAPI, …            [edit]   From your CV
Never changed in your CV Acme · Backend Engineer · B.Sc. …      From your CV

A few answers forms often need           (nothing is sent until you answer)
  Authorized to work in Egypt?            [Yes] [No] [Ask me]
  Demographic questions (gender, race…)   [Prefer not to say for all] [Ask me each time] [Answer now]
  Salary expectation (EGP)                [        ]  optional · Ask me
```

### 5.4 Screen 4: What jobs?

```
Jobs like                [Backend Engineer ✓] [Python Developer ✓] [Software Engineer] [+ add]
Level                    Mid · Senior                                 From 5 years in your CV
Where                    [Egypt ✓] [+ add]     [✓] Include remote jobs
Kind of jobs             Tech ✓  ·  Change                              From your skills
Sources                  Wuzzuf, Forasna, Bayt, LinkedIn, Indeed + 120 company boards   Change

                 [ Find jobs (practice mode, nothing is submitted) ]
```
The button starts discover → score and opens Home with live progress.

### 5.5 Readiness rules (one source of truth)

The server computes `setup_state = {required_done, next_step}` once. The UI uses it for the Home card, the step
ticks and the Start buttons. Required = CV approved + AI tested + at least one role + Where. LibreOffice is
required *before tailoring*, not before searching, so it shows as a Home task ("Needed before applying"), not a
blocker. The global banner is replaced by a nav chip: "Setup 3/4".

---

## 6. Just-in-time setup (ask when it matters, with the job as the reason)

| Trigger | Card in "Needs you" | Asks for | Remembers |
|---|---|---|---|
| The first job that needs an account | "Acme's site needs an account. LinKit can create it and save the password safely." | Vault passphrase (once, with a show toggle; the repeat field is dropped, a strength meter is added) + "Connect Gmail" (app password, with a 3-step how-to and a link) | Vault unlocked + IMAP/SMTP |
| The first email application | "This job asks you to apply by email." | Gmail is already connected → just confirm; not connected → the same Gmail card | — |
| The user enables a source that needs a key | Inline on the source row | The key, with a "Get a free key" link | Vault (asks for the passphrase if it isn't made yet) |
| The first unknown question | The existing answer card | The answer + **"Use this for similar questions"** (on by default) | Answer bank |
| The first privacy-notice checkbox | "Accept privacy notices like this one?" | **This job only / Always / Ask me each time** | `acknowledge_privacy` |
| The first legal declaration | The same pattern, default "Ask me each time" | — | `acknowledge_legal` |
| The first notice-period question | A select | — | profile |
| The user turns on LinkedIn posts | The existing risk warning + sign-in button | — | — |

Rule: a just-in-time card never blocks other jobs. Only that job waits.

---

## 7. Information architecture

```
Home        next best action · progress · today's numbers · "Search every day at 09:00" toggle
Jobs        all jobs, filters, job detail (unchanged, plus a reason chip)
Needs you   [Approve jobs] [Finish applications]   ← Review + Action Center (one badge)
Activity    [Now] live events + screenshot view · [History] runs + report + export
Settings    Profile & CV · Jobs & places · Sources · Answers (answer bank) · Applying (Pace, Live) ·
            Accounts & email (vault, Gmail, keys) · AI · Advanced · Language & notifications
```
- `''` → Home. Home sends a new user to the first run.
- The old routes (`/review`, `/actions`, `/live`, `/report`, `/vault`, `/answers`, `/setup`) redirect to the new
  tabs so the notification links and docs keep working (`deep-linking`, `back-stack-integrity`).

### 7.1 Home: one place answers "what now?"

```
┌ Next ──────────────────────────────────────────────────────────┐
│ 14 possible matches are waiting for you.   [ Review them ]      │
└────────────────────────────────────────────────────────────────┘
Found 1,240 → passed filters 310 → strong 22 · possible 14 → applied 9 (practice)
Last search: today 09:00 · next: tomorrow 09:00   [✓] Search every day at [09:00]
Tasks: ☐ Install LibreOffice (needed before applying)  ☐ Ready to apply for real? (8.2)
```
The funnel numbers are links into Jobs with a matching filter, so the numbers teach the pipeline (learnability).

---

## 8. Running and going live

### 8.1 Smart primary button (D9)

| State | Label |
|---|---|
| Setup not done | Finish setup (step 3 of 4) |
| No jobs yet | Find jobs |
| A run is going | Searching… 640 found · Stop |
| Possible matches waiting | Review 14 possible matches |
| Approved or strong jobs queued | Apply to 9 jobs (practice) / Apply to 9 jobs |
| Nothing queued | Find new jobs |

Unfinished runs resume automatically. "Start fresh" and the stage checkboxes move to Activity → Advanced.

### 8.2 Guided unlock for Live mode (D10)

After the first practice run with at least one filled form:
1. A Home task appears: "Ready to apply for real?"
2. The card shows the screenshots of 3 filled forms + the tailored CV diff for one job.
3. Checklist: CV approved · sensitive answers set or on "Ask me" · daily caps (Pace) · "Confirm each submission" **on**.
4. The button "Turn on real applications" confirms with the action named ("Submit real applications from now on?").
5. "Submit without asking" stays a separate Advanced switch with its current warning.

The header badge changes from **Practice mode** to **Applying for real**, the same words everywhere.

---

## 9. Vocabulary (one name everywhere; EN and AR need a native check)

| Concept | Old | New EN | New AR |
|---|---|---|---|
| Dry run | Dry run | Practice mode | وضع التجربة |
| Live | Live | Applying for real | تقديم فعلي |
| Tier high / mid / low | high / mid / low | Strong / Possible / Weak match | تطابق قوي / محتمل / ضعيف |
| Action Center + Review | Action Center, Review queue | Needs you | بانتظارك |
| Run | Run | Search | بحث |
| Stage | Stage | (hidden; Advanced only) | — |
| Vault | Vault | Saved passwords (vault) | كلمات المرور المحفوظة |
| Locked facts | Locked facts | Never changed in your CV | لا يتغير في سيرتك |
| Answer bank | Answer bank | Saved answers | الإجابات المحفوظة |
| Ghost job | Ghost job | Stale posting | إعلان قديم |

Code names (`dry run`, `tier`, `needs_user`…) stay. This is UI copy only; `i18n/en.ts` + `ar.ts`.

---

## 10. "Needs you": batch resolve

- **Approve jobs** tab (old Review): card list, J/K/A/S/O keys, bulk approve with a 10 s Undo, and the reason
  and missing skills on each card.
- **Finish applications** tab (old Action Center): **group parked items by question** (fuzzy match on the label,
  the same rapidfuzz/embedding match the answer bank uses). "9 applications ask: *What is your notice period?*"
  → answer once → all 9 retry. CAPTCHA, login and 2FA stay one per item, sorted by site.
- Each card follows one pattern: **what happened · why · one primary fix button** (`error-recovery`).
- Empty state: "Nothing needs you. LinKit will tell you when something does." + the notification toggle inline.

---

## 11. Learnability and memorability features

1. **Source badges** on every derived value. Users learn *why* a setting is what it is.
2. **Reason chips** on filtered and low jobs ("Filtered: title has 'intern'"), plus "Show me why" in the job detail.
3. **Funnel numbers as links** on Home: clicking teaches the pipeline without a tutorial.
4. **"Changed" marks** in Advanced + a "Reset to preset" link. It's safe to explore.
5. **First-time hints**: one dismissible line per page on the first visit only (e.g. "Possible matches wait here
   for your yes or no"). They're kept in `localStorage`, a per-viewer convenience.
6. **Keyboard shortcuts** in Needs you, with a `?` cheat sheet.
7. **The same button names on every screen** (*Approve*, *Skip*, *Retry*, *Open the page*), with verbs first (UX copy).
8. **The weekly return path**: notifications say exactly one thing to do ("3 applications need you"), and the click
   lands on that tab.

---

## 12. Roadmap (build order; sizes are agent working time, with tests)

| Phase | What | Main files | Size |
|---|---|---|---|
| **UX1** | Inference layer + presets + CV contact/section/date rules + AI gap fill | new `core/infer.py`, `core/presets.py`; `core/profile.py`; tests with EN/AR CV fixtures | 2 days |
| **UX2** | 4-screen first run + "Check what we found" + readiness state | new `pages/welcome.ts`; `api/routes.py` (`/setup/state`, `/infer`) | 2 days |
| **UX3** | Settings reorg + autosave + Pace/Pickiness presets + Advanced + one "Where" | split `pages/setup.ts` (1068 lines) into `pages/settings/*.ts` | 2 days |
| **UX4** | IA: Home + smart button + 5-item nav + redirects + vocabulary rename EN/AR | `app.ts`, `app.routes.ts`, new `pages/home.ts`, `i18n/*` | 2 days |
| **UX5** | Just-in-time cards (vault, Gmail, keys, privacy/legal/notice) + batch resolve in Needs you + per-job sponsorship rule | `pages/actions.ts`, `apply/answers.py`, `api/routes.py` | 2–3 days |
| **UX6** | Guided Live unlock + review shortcuts/undo + reason chips + first-time hints | `pages/review.ts`, `pages/home.ts`, `pages/jobs.ts` | 1.5 days |
| **UX7** | Usability round (section 14) + fixes | — | 1 week calendar |

UX1 goes first: every later screen only renders what it produces. UX3 and UX4 can run in parallel after UX2
(they touch different files).

---

## 13. CLAUDE.md edits this plan needs (on approval)

- §5.5 Screening questions: sponsorship is answered per job from `authorized_countries` + the job country; unknown country → Action Center.
- §5.7 Action Center: shown as "Needs you" (with Review); parked items grouped by question.
- §6 Vault: created just in time (the first account or Gmail), not in setup. The crypto is unchanged.
- §7 UI screens: replace the list with section 7 of this file.
- §10 Build order: add Phase 12 (UX1–UX7).

---

## 14. Validation plan (no telemetry: moderated sessions only)

- **Who**: 5 people. 3 non-tech MENA job seekers (one Arabic-UI user), 2 developers. A fresh Windows machine, the app installed.
- **Tasks**: (1) get from install to the first search; (2) find out why a job was filtered; (3) answer a question
  that 4 parked applications share; (4) turn on real applications; (5) **7 days later**, come back and approve +
  apply without help (memorability).
- **Targets**:

| Metric | Today (estimate) | V1 target |
|---|---|---|
| Time from CV upload to the first search started | 15–30 min | **≤ 3 min** |
| Required decisions before the first search | ~25+ | **≤ 5** |
| Task success (tasks 1–4), no help | — | ≥ 80 % |
| Task 5 success after 7 days | — | ≥ 4 of 5 |
| SUS score | — | ≥ 75 |
| Derived CV fields correct before edits | — | ≥ 90 % on the fixture set (EN + AR) |

- **Method**: think-aloud, 45 min (5 warm-up, 30 tasks, 10 debrief), an affinity map of the notes, then an
  impact/effort sort into UX7 fixes.

---

## 15. Still open (small; defaults chosen, change any)

| # | Question | Default in this plan |
|---|---|---|
| Q1 | Egyptian and Gulf Telegram channel lists: who curates them? | Ship empty for MENA until you give a list; the Russian defaults only apply to region "Other" + track Tech |
| Q2 | Do internships count toward years of experience? | Excluded (the title contains *intern/trainee*) |
| Q3 | Outlook users: Gmail-only message now, or hide email apply? | Show "Outlook isn't supported yet" at the Gmail card |
| Q4 | Keep the setup wizard reachable for power users? | No. Settings has everything; "Run first-time setup again" sits in Settings |

---

## 16. Execution (orchestrator log)

Started 2026-10-29. Orchestrator plans and reviews; Sonnet executors build; Haiku assistants search and browser-test.

### 16.1 Extra decisions (maintainer, 2026-10-29)

- §13 CLAUDE.md edits and Q1–Q4 defaults: **approved**.
- Git: **one commit per phase on main** (UX1 … UX6), message style `UX1: <summary>`.
- Arabic: **executors write AR for every new/renamed key** (terms from section 9); list new terms at the end for a native check.
- Old wizard: **delete `pages/setup.ts`**; `/setup` redirects (first run if not ready, else Settings).

### 16.2 Decisions made by orchestrator (override any)

- An explicit `needs_sponsorship` (Yes/No) still wins; only when it is "Ask me" (None) is sponsorship derived per job
  from `authorized_countries` + `country_of(job_location)`; unknown country → Action Center.
- Country data: reuse `apply/answers.py` `_COUNTRIES` / `country_of` / `canonical_country`; no new country/city tables
  beyond what `core/presets.py` needs (currency, jobspy key, region, boards).
- No new dependencies (no `phonenumbers`); regex + small lexicons in code.
- Inference values are stored nowhere until the user confirms: `GET /api/infer` computes, `POST /api/infer/apply` writes.
- AI gap fill: one LLM call through the configured `LLMProvider`, non-sensitive fields only, values flagged `check=true`.
- Frontend tasks run **sequentially** (they all touch `i18n/en.ts` + `ar.ts`); backend UX1 tasks run in parallel.
- Fix found during mapping: `resolve_action` writes to the answer bank before checking the item is open (routes.py:880-887) → fixed in UX5.

### 16.3 Global constraints (every brief)

1. CLAUDE.md §2 hard rules: no fabricated CV content; sensitive categories never sent to the AI and never auto-answered; no telemetry; never log CV text, passwords or tokens.
2. No new Python or npm dependencies. Type hints everywhere; `uv run ruff check src tests`, `uv run mypy src` clean.
3. Tests for every new logic path (`uv run pytest tests/unit -q`); no live-site calls; synthetic CV fixtures built in tests with python-docx.
4. Frontend: Angular 21 standalone components + signals, existing classes in `frontend/src/styles.css`, all text via the `t` pipe with keys in **both** `i18n/en.ts` and `i18n/ar.ts`; RTL-safe (`dir="auto"`, `<bdi>`). `cd frontend && npx ng build` clean.
5. Match surrounding code: comment density, naming, helpers (`lines`, `unlines`, `Api`, `I18n`).
6. Code names stay (`dry run`, `tier`, `needs_user`); only UI copy changes (section 9).

### 16.4 Tasks

| Id | Phase | Task | Depends | Status |
|---|---|---|---|---|
| T1.1 | UX1 | `core/presets.py`: country, track, Pace, Pickiness presets + tests | — | done (2777e78) |
| T1.2 | UX1 | `core/infer.py`: CV rules (contacts, links, name split, location, experience/years, current role, skills, locked facts, track, queries, seniority, title_exclude) + EN/AR tests | T1.1 interface | done (2777e78) |
| T1.3 | UX1 | Per-job sponsorship rule in `apply/answers.py` + tests | — | done (2777e78) |
| T1.4 | UX1 | API: `GET /infer`, `POST /infer/ai-fill`, `POST /infer/apply`, `GET /setup/state`, "where" writer + tests; commit UX1 | T1.1, T1.2 | done (2777e78) |
| T2.1 | UX2 | `pages/welcome.ts` 4-screen first run; `''`/`/setup` routing; commit UX2 | T1.4 | done |
| T3.1 | UX3 | Settings shell + autosave helper + Profile & CV, Jobs & places (one Where), AI sections | T2.1 | done |
| T3.2 | UX3 | Settings: Sources (recommended filter), Answers (bank merged), Applying (Pace, Live), Accounts & email (vault, Gmail, keys), Advanced (Pickiness, raw knobs, changed marks); delete `setup.ts`, `answers.ts`, `vault.ts` pages; commit UX3 | T3.1 | done |
| T4.1 | UX4 | Home + smart button + 5-item nav + Activity (Live + Report tabs) + Needs you (Review + Actions tabs) + redirects + vocabulary rename EN/AR; commit UX4 | T3.2 | todo |
| T5.1 | UX5 | Backend: JIT park kinds (vault/email needed), batch answer API, privacy/legal "always" option, resolve_action fix + tests | T1.4 | done |
| T5.2 | UX5 | Frontend: grouped Needs you, JIT cards, undo toast, J/K/A/S/O shortcuts; commit UX5 | T4.1, T5.1 | todo |
| T6.1 | UX6 | Guided Live unlock, reason chips on Jobs, first-time hints; commit UX6 | T5.2 | todo |
| T7.1 | — | CLAUDE.md §13 edits (≤ 200 lines), handoff.md note | T6.1 | todo |
| T7.2 | — | Browser E2E pass (Haiku) on a fresh data dir + full test suite | T7.1 | todo |

### 16.5 Log

- T1.1: `enabled` source presets are hard-coded curated name lists (registry has no region/tech metadata) + a registry-sync test. Pace "fast" = 3 sites, 10–30 s, 40/day, 25/run; "careful" = 1 site, 60–120 s, 10/day, 5/run.
- T1.3: sponsorship compares the country the question names, else the job's country.
- T1.4: AI-filled values come back as level "suggest", check true; stored in `<cv dir>/infer_ai.json` keyed by CV hash.
- UX1 committed 2777e78. T2.1 and T5.1 running in parallel (frontend vs backend, no shared files).
