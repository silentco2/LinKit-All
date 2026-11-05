# UX plan and audit: LinKit All V1

Written 2026-10-29, brought up to date 2026-11-05. Status: **UX1–UX6, round 2, the UX7 fixes and U15–U18 are built.**
What is left: the study with real people, merging the Outlook branch (section 12).
Goal: make the app **simple, usable, learnable and memorable**, and get a new user from install to the first
job search with as few inputs as possible, with no invented answers (CLAUDE.md §2 applies to everything).

Read with `CLAUDE.md` (binding rules), `plan.md` and `handoff.md`.

---

## 0. TL;DR

| | Before | Now |
|---|---|---|
| Setup screens | 10 tabs, 2 rows, no Next/Back | 4 first-run screens at `/welcome`; the rest is Settings or asked just in time |
| Controls shown before the first search | ~90, plus ~100 source checkboxes | **5 decisions** (CV, AI, confirm profile, roles + places, start). The simulated round measured a median of 6 |
| Suggestions | free text everywhere | offline lists (GeoNames cities, O*NET titles and skills) behind tag/chip inputs; tap-to-add recommendations |
| Where to work | 4 location fields, Indeed country as text | **one places list**; each place is "I can work here", "I'd need a visa" or unanswered |
| Fields asked twice | name, location, country, currency ×3, email, company, title, links | each asked once, or derived; name typed once; home address and international phone in the profile |
| CV upload | filled nothing | fills empty non-sensitive fields; employers, titles and degrees are protected automatically |
| Save buttons | ~12 | 0: autosave with a "Saved" tick |
| Nav items | 8 | 5: Home, Jobs, Needs you, Activity, Settings |
| Starting a run | 5 stage checkboxes + "new vs resume" | 1 smart button that follows the state, plus an "Apply to N jobs" button; a line per job while applying |
| Going live | a checkbox anytime | "Ready to apply for real?" in Home's main card, with real checks, screenshots, the CV red-line and a named confirm |
| AI limits | raw vendor error, run "failed" | one plain message, run paused, "use another AI" |
| LibreOffice | red box, `linkit doctor` | optional; one-click install from the hosted bundle (Windows x64) or use the CV as it is |
| Privacy | "everything stays on this computer" | the exact list of what leaves it ("What leaves this computer") |
| Arabic | partly English at run time | one numeral system, six plural forms, translated reasons, errors and log lines |

The core is a **rule-based inference layer** (section 4): the CV, the places and the target roles derive nearly
every other setting. Each derived value shows its source and stays editable.

---

## 1. Decisions (maintainer)

| # | Date | Topic | Decision |
|---|---|---|---|
| D1 | 2026-10-29 | Persona | **Both** tech and non-tech. The track is pre-selected from the CV: one tap, not a question |
| D2 | 2026-10-29 | CV parsing | **Rules first, AI fills the gaps.** AI-filled values are marked "check this" and must be verbatim from the CV |
| D3 | 2026-10-29 | Work authorization | Never assumed. Now set per place (D17). Sponsorship is worked out per job |
| D4 | 2026-10-29 | Vault | **Asked only when first needed** (first account sign-up or adding Gmail) |
| D5 | 2026-10-29 | Navigation | **Review + Action Center = "Needs you".** Nav: Home, Jobs, Needs you, Activity, Settings |
| D6 | 2026-10-29 | Terms | **Plain words** (section 9) |
| D7 | 2026-10-29 | Saving | **Autosave** with a "Saved" tick. Risky switches still confirm |
| D8 | 2026-10-29 | Salary | One expectation used only to answer forms; the filter floor is a separate opt-in. Refined by D21 |
| D9 | 2026-10-29 | Run control | **One smart button** on Home. Resume is automatic; stages are under Advanced |
| D10 | 2026-10-29 | Live mode | **Guided unlock** after the first practice run |
| D11 | 2026-10-29 | Tuning knobs | **Presets** (Pace, Pickiness) **+ a collapsed Advanced section**; changed values are marked |
| D12 | 2026-10-29 | Q1 | Egyptian and Gulf Telegram lists: the first curated MENA tech channels shipped (947d891). Other lists still to curate |
| D13 | 2026-10-31 | Q2 | **Internships DO count** toward years of experience (first "excluded", changed 2026-10-31) |
| D14 | 2026-10-31 | Q3 | Outlook: built in its own session on branch `claude/outlook-oauth-898770` (f0214e3). **Not merged.** Needs an Azure client id |
| D15 | 2026-10-29 | Q4 | No wizard for power users. Settings has everything; "Redo first-time setup" sits in Settings |
| D16 | 2026-10-29 | AI language | AI writes **English only**. Job details are never translated (copied verbatim). English variants of multi-language sources are kept |
| D17 | 2026-11-01 | Places | One list: **allowed / visa / unanswered**. Work rights are never assumed. Home country and old-config places start unanswered |
| D18 | 2026-10-29 | Arabic plurals | `Intl.PluralRules`: zero/one/two/few/many/other in the UI (39a7e3f) |
| D19 | 2026-10-31 | Offline data | GeoNames (countries, cities) and O*NET (titles, skills) ship with the app; `/api/suggest` reads them |
| D20 | 2026-10-31 | Exchange rates | A shipped table, refreshed from open.er-api.com at each search (only a currency code is sent) |
| D21 | 2026-10-31 | Salary | **One monthly expectation** plus an opt-in "skip lower". Postings in other currencies are converted |
| D22 | 2026-10-31 | LinkedIn posts | One quiet note, no checkbox. Google search, no LinkedIn login (9d033de) |
| D23 | 2026-10-31 | Sensitive answers | Nationality, date of birth, marital status and military status are sensitive: "Ask me", never sent to the AI |
| D24 | 2026-10-31 | CV upload | Fills empty non-sensitive fields. Locked facts are automatic (no "never changed" input) |
| D25 | 2026-11-01 | Browser | **One Show/Hide setting** for every browser LinKit runs |
| D26 | 2026-11-01 | LibreOffice | **Optional one-click install.** Declining means the original CV is used, no tailoring. **Practice works without LibreOffice** |
| D27 | 2026-11-01 | Testing | **No more simulated users.** Further findings come from the maintainer |
| D28 | 2026-11-05 | Level tips | Level chips explain themselves in **hover/focus tooltips** (maintainer's choice), not inline text |
| D29 | 2026-11-05 | Source names | Added sources are named **"Company · platform"** (60b9c97) |
| D30 | 2026-11-05 | Work rights | A work right **belongs to the country**: a new place in a listed country inherits it, a change applies to all its rows (52b068e) |
| D31 | 2026-11-05 | LibreOffice bundle | **Hosted on the GitHub release** `libreoffice-26.2.6-win-x64` of silentco2/LinKit-All, with a pinned SHA-256 (dfb7c26). Verified with a real install |

---

## 2. How this audit was done

- **Code read**: the old `pages/setup.ts` (1068 lines, now deleted), `app.ts`, routes, `i18n/en.ts`, and the models in
  `core/search.py`, `core/profile.py` and `apply/answers.py`.
- **App run** on a fresh data dir, then a browser E2E pass after UX6 (10 of 10 flows), then a simulated usability round (section 14).
- **Frameworks**: design critique, UX copy, the UI/UX Pro Max rule base, Nielsen's 10 heuristics.
- **Out of scope on purpose**: visual polish, colour contrast, a full accessibility pass.

---

## 3. Findings and status

Severity: 🔴 blocks or tires new users · 🟡 slows or confuses · 🟢 polish.
Status: **Fixed** (built as planned) · **Changed** (solved a different way) · **Open**.

### 3.1 Onboarding

| # | Finding | Sev | Status |
|---|---|---|---|
| O1 | 10 setup tabs, no Next/Back, no "step x of y" | 🔴 | **Fixed** 4-screen first run with "Step n of 4" (4d96adc) |
| O2 | Name, email, phone and location asked before the CV, then again in Answers | 🔴 | **Fixed** inference + CV autofill + name typed once (2777e78, ea22b5e, ec1d220) |
| O3 | Location typed 4 times (profile, search, filter, Indeed country as free text) | 🔴 | **Fixed** one places list; Indeed's country comes from it (dd5e4d2, bc15cd3) |
| O4 | Currency typed 3 times | 🟡 | **Fixed** one currency from the home country, listed first (ec1d220, 92709c3) |
| O5 | ~100 source checkboxes, all off | 🔴 | **Changed** presets pick the sources; one grouped "Job sources" list with a recommended filter and an Add-a-source box (da96a87, bc15cd3) |
| O6 | Telegram defaults were Russian-language channels | 🔴 | **Fixed** per country/track lists; first MENA tech channels curated (2777e78, 947d891). Other lists: see Q1 |
| O7 | Vault, Email and API keys as three main-flow steps | 🔴 | **Fixed** just-in-time cards (3c9ae0c, 60eb327) |
| O8 | Step ticks never ticked or ticked too early | 🟡 | **Fixed** one server rule `setup_state` (4d96adc) |
| O9 | "Setup isn't finished" banner on the setup page itself | 🟢 | **Fixed** replaced by a "Setup n/4" chip on Settings (986969a) |
| O10 | Checklist shows LibreOffice ✗ while Start is enabled | 🟢 | **Changed** LibreOffice is optional; practice works without it (ba46591, 717f827) |
| O11 | First visit lands on empty Jobs | 🟡 | **Fixed** `''` → Home; a new user goes to `/welcome` (4d96adc) |
| O12 | AI step: separate Test and Save, free-text model | 🟡 | **Fixed** auto-detect, auto-test on pick (4d96adc) |
| O13 | 24 answer fields in one form | 🔴 | **Fixed** 4 derived, a few one-tap, the rest just in time (2777e78, 60eb327) |

### 3.2 Saving and feedback

| # | Finding | Sev | Status |
|---|---|---|---|
| F1 | Seven Save buttons all `PUT` the whole config | 🔴 | **Fixed** autosave per field (da96a87) |
| F2 | Unsaved edits lost on leaving | 🟡 | **Fixed** autosave |
| F3 | Raw server errors in a banner far from the field | 🟡 | **Fixed** inline errors under the field (da96a87) |
| F4 | One shared banner per page | 🟢 | **Fixed** per-field "Saved" tick |

### 3.3 Information architecture

| # | Finding | Sev | Status |
|---|---|---|---|
| I1 | 8 flat nav items | 🟡 | **Fixed** 5 items (986969a) |
| I2 | Two places for answers, two for the vault | 🟡 | **Fixed** one home each under Settings (da96a87) |
| I3 | Live run mixes control, schedule, activity and screenshots; Report is separate | 🟡 | **Fixed** Activity = Now + History (986969a) |
| I4 | No home; nothing answers "what now?" | 🔴 | **Fixed** Home with the smart button (986969a) |
| I5 | Schedule hidden inside Live run | 🟡 | **Fixed** one-line daily toggle on Home |

### 3.4 Running and applying

| # | Finding | Sev | Status |
|---|---|---|---|
| R1 | 5 stage checkboxes expose the pipeline | 🟡 | **Fixed** smart button (986969a) |
| R2 | "New run vs resume" asks users to reason about internals | 🟡 | **Fixed** auto-resume; "Start fresh" in Advanced |
| R3 | Live mode is one checkbox with no proof practice worked | 🔴 | **Fixed** guided unlock (6ee5dc3); checks made real and the confirm made safer (ba46591, 717f827) |
| R4 | Start enabled while setup is unfinished | 🟢 | **Fixed** the button says what is missing |

### 3.5 Review and Action Center

| # | Finding | Sev | Status |
|---|---|---|---|
| A1 | 9 jobs ask "notice period", the user answers 9 times | 🔴 | **Fixed** grouped by question (3c9ae0c, 60eb327) |
| A2 | No undo on bulk approve | 🟡 | **Fixed** 10 s Undo (60eb327) |
| A3 | No keyboard flow | 🟢 | **Fixed** J/K/A/S/O/X and a `?` cheat sheet (60eb327) |
| A4 | A filtered or low job doesn't say why | 🟡 | **Fixed** reason chips (6ee5dc3); the reason links to its setting (92709c3) |

### 3.6 Copy and terms

| # | Finding | Sev | Status |
|---|---|---|---|
| C1 | Mixed vocabulary | 🟡 | **Fixed** section 9 (986969a) |
| C2 | Implementation details in hints | 🟡 | **Changed** moved to Advanced or removed (da96a87, a11af9f); not re-audited line by line |
| C3 | "/" split syntax only in a hint | 🟢 | **Fixed** tag inputs split into chips (ea22b5e) |
| C4 | CV intro is 4 sentences about formats | 🟢 | **Fixed** short drop zone text (4d96adc) |

### 3.7 Found by the simulated round (details: `docs/usability/simulated-round-1.md`)

U1–U14 are in the round file. U15–U18 and the smaller items are now fixed:

| # | Finding | Sev | Status |
|---|---|---|---|
| U15 | Go-live entry is a small link; no CV red-line diff | 🟡 | **Fixed** go-live in Home's main card with the red-line (d821983; lightbox in 717f827) |
| U16 | Internal words: "Practised", "Find new jobs" label, raw state names | 🟡 | **Fixed** plain words, "Connected to Claude", states mapped to user words (d821983, 60b9c97; buttons in 717f827) |
| U17 | Silent apply runs, raw log lines, no "stopped" notice | 🟡 | **Fixed** a line per job, a Stopped state, plain errors with Details (d821983, 93637ec) |
| U18 | Needs-you cards carry 5–8 controls and no clear main button | 🟡 | **Fixed** one main button per card kind, the rest in a More menu; choice answers save explicitly (52b068e) |
| – | Smaller items: practice badge on welcome (d821983) · level tips (52b068e) · work rights per country, so no second Riyadh question (52b068e) · select-all focus and undo key (92709c3) · two-step Backspace on tags (52b068e) · added source named "Company · platform" (60b9c97, 52b068e) · job history dates (52b068e) · shareable job URL (92709c3) · flags hidden where Windows can't draw them (52b068e) · PDF name shown after upload (52b068e) · Home "Next" counts the approve queue (52b068e) | 🟢 | **Fixed** |

Remaining limits:
- No `daily_cap` per-job event. Jobs over the daily cap are skipped before a run starts, so Activity has no line for them.
- Level tips show on hover and focus only. Touch screens get no tip.
- Place picker: Enter now picks the first suggestion; unmatched text in the places list shows a hint (fixed in 46d5521).

### 3.8 What already works well (keep)

- The "Ask me" default for sensitive answers; "never sent to the AI" was praised.
- The PDF → DOCX approval gate and the CV segment preview.
- Live badges for review and actions counts, desktop notifications, EN/AR with RTL.
- Practice mode, the grouped answer, funnel numbers as links, source badges, blunt confirm text.

---

## 4. The inference layer (rule-based, no invented answers)

### 4.1 Confirmation levels

Each value shows a source badge: **From your CV · From your country · From your roles · You set this**.

| Level | Meaning | UI |
|---|---|---|
| **Auto** | Derived by a rule, low risk, shown and editable | Filled in, with a source badge |
| **Suggest** | Derived, but the user taps to accept | A question with the suggestion as a button; unused until tapped |
| **Ask** | Never derived (§2) | Left on "Ask me"; asked just in time (section 6) |

AI-filled CV values are **Suggest + "check this"**, and must be verbatim from the CV (checked). Nothing is written until the user confirms (`GET /api/infer` computes, `POST /api/infer/apply` writes). A CV upload then fills only **empty, non-sensitive** fields.

### 4.2 Field map

Inputs the user gives: **CV file, AI choice, roles (confirm), places (confirm), track (confirm)**.

| Setting | Derived from | Rule | Level |
|---|---|---|---|
| `full_name` | CV | Top of page 1. Typed once; first/last name derived | Auto |
| `email`, `phone` | CV | Regex + DOCX hyperlinks. Phone is international, picked with a country-code picker | Auto |
| home address (address, city, country, postal code) | CV header | City matched against the offline GeoNames list (EN + AR). Address and postal code also fill forms | Auto |
| `linkedin`, `github`, `portfolio` | CV | URL regex + hyperlink targets. Shown as "read from your CV" with **Use it** | Auto |
| `current_company`, `current_title` | CV | The entry whose date range ends in *Present / Current / Now / حتى الآن* | Auto |
| `years_experience` | CV | Union of experience date ranges. **Internships count** (D13) | Auto |
| level (seniority) | years + **title words** | Band from years; a title that names a level (*Senior, Lead, Manager*) sets it. Years alone never infer manager or executive. Internship-only CVs get an intern/junior level | Auto |
| `locked_facts` | CV | Every employer, title, degree and institution is protected **automatically**. There is no input for it (D24) | Auto |
| `skills` | CV | The skills section only, plus a known-skills lexicon; links like "github" are not skills. Shown as tags with O*NET suggestions | Auto |
| track | skills + titles | Tech vs General | Suggest |
| `search.queries` | CV titles | Current and past titles, seniority words removed, max 5, as tap-to-add recommendations | Suggest |
| places | CV country + remote | **One list.** Each place: allowed / visa / unanswered (D17). Search places, filter places, Indeed's country, `authorized_countries` and the visa list are all written from it | Auto / Ask |
| work rights | — | **Never assumed.** Only an explicit choice adds a country to the authorized or visa list | Ask |
| `needs_sponsorship` | places + **job country** | Left on "Ask me" → per job: job country allowed → No; visa → Yes; unknown country → Needs you | Rule, per job |
| `sources.*` | country + track | Preset tables (4.4); LinkedIn keywords default to your job titles | Auto |
| currency | home country | One currency, listed first in the selector | Auto |
| salary | — | One **monthly** expectation, optional, "Ask me" by default. Opt-in "skip lower" filter; postings are converted with the FX table (D20, D21) | Ask |
| `email.imap_*`, `smtp_*` | email domain | Gmail → Google; Yahoo → Yahoo; Outlook → needs the OAuth branch (D14) | Auto |
| `answers.heard_about` | the job's source | Per job: "LinkedIn", "Wuzzuf", "Company website"… | Auto |
| notice period | — | Just-in-time select (Immediately … 3 months), saved to the profile | Ask |
| nationality, date of birth, marital status, military status | — | **Sensitive.** "Ask me", never sent to the AI (D23). Military status answers Egyptian service questions; it is not US veteran status | Ask |
| EEO | — | One row: Prefer not to say for all / Ask me each time / Answer now. "Hispanic" removed from the race list | Ask |
| `acknowledge_privacy`, `acknowledge_legal` | — | Just in time: This job only / Always / Ask me each time | Ask |
| AI provider | PATH scan | One CLI found and signed in → pre-selected and auto-tested | Auto |
| Tiers, AI max, batch | Pickiness preset | Strict 9/6 · Balanced 8/5 · Wide 7/4 | Auto |
| Apply pace/caps/parallel | Pace preset | Careful · Balanced · Fast (values in `core/presets.py`) | Auto |

Home: `core/infer.py` (pure functions) and `core/presets.py` (tables as data), unit-tested with EN and AR CV fixtures.
The UI never invents; it only renders `Inferred`.

### 4.3 One "Where" concept

Users think "where do I want to work", not "search vs filter vs Indeed country". The roles screen has one **places**
picker over the offline city list (EN + AR) plus the three work-mode chips and a posted-within chip. Each place gets a
work-rights choice. The backend writes every derived list from it. The raw lists stay in Advanced.

### 4.4 Preset tables (data, not code)

| Region | Regional boards | jobspy | Currency | Telegram |
|---|---|---|---|---|
| Egypt | Wuzzuf, Forasna, Bayt | LinkedIn, Indeed, Google | EGP | first curated MENA tech channels (947d891) |
| Gulf (SA, AE, QA, KW, BH, OM) | Bayt (Naukrigulf when unblocked) | LinkedIn, Indeed, Google, Glassdoor | local | to curate |
| Other | — | LinkedIn, Indeed, Google, Glassdoor | local | none |

| Track | Extra sources on |
|---|---|
| Tech | ATS feeds, remote-job aggregators, tech boards |
| General | Regional boards + aggregators that aren't tech-only |

Everything stays editable in **Settings → Sources**: one grouped list (job sites, regional, aggregators, boards,
companies, Telegram), a "Recommended for you" filter, and an **Add a source** box for Telegram links or careers pages (`POST /sources/add`).

---

## 5. First run: 4 screens

"Step n of 4", Back on every screen. All inputs are autosaved; nothing derived is written until confirmed.

| # | Screen | What it shows |
|---|---|---|
| 1 | **Add your CV** | Drop zone (Word, PDF, ODT, LaTeX), language switch, short privacy line with the "What leaves this computer" panel. The PDF conversion approval stays here. LibreOffice is **optional** and not asked here (section 5.3) |
| 2 | **Connect your AI** | Detected CLIs get a "Found on this computer" badge; one is pre-selected and auto-tested. Picking a card tests it. A usage-limit error is one translated sentence with a "use another AI" button. The AI then fills CV gaps in the background |
| 3 | **Check what we found** | One card, every value with a source badge: name, phone (country-code picker), home address, current work, links, skills as tags. Sensitive answers: demographics row, monthly salary (muted example placeholder). **No** "never changed" row and **no** authorized-to-work question |
| 4 | **What jobs?** | Job titles as tags with O*NET suggestions and tap-to-add recommendations · level chips · **places with work rights** · work modes · track (Tech / General) · sources summary · "Find jobs (practice mode, nothing is submitted)" |

### 5.1 Screen 3 sketch

```
You          Sara Ahmed · sara@… · +20 …                    From your CV
Home         12 Nile St, Cairo, Egypt · 11511               From your CV
Now          Backend Engineer at Acme · 5 years             From your CV  ⚠ check this
Links        linkedin.com/in/… · github.com/…               From your CV   [Use it]
Skills       [Python] [FastAPI] [+ add]                     From your CV

A few answers forms often need           (nothing is sent until you answer)
  Demographic questions   [Prefer not to say for all] [Ask me each time] [Answer now]
  Monthly salary (EGP)    [ e.g. 30,000 ]   Ask me by default
```

### 5.2 Screen 4 sketch

```
Jobs like   [Backend Engineer ✓] [Python Developer ✓] [+ add]
Level       [Mid ✓] [Senior ✓]                          From 5 years in your CV
Places      [Egypt · I can work here] [Dubai · I'd need a visa] [Riyadh ?] [+ add]
Work mode   [Onsite] [Hybrid] [Remote]       Posted within [7 days]
Kind        Tech ✓ · Change                              From your skills
              [ Find jobs (practice mode, nothing is submitted) ]
```

### 5.3 Readiness (one source of truth)

The server computes `setup_state = {required_done, next_step}`. Required = CV approved + AI tested + at least one role + a place.
LibreOffice is **never required**: practice works without it, a real run that needs it is refused up front with a code,
and declining means the original CV is used for every job (D26). It shows as one card (install for me, a one-click 145 MB download on Windows x64 /
get it / check again / use my CV as it is). No terminal commands.

---

## 6. Just-in-time setup (ask when it matters, with the job as the reason)

| Trigger | Card in "Needs you" | Asks for | Remembers |
|---|---|---|---|
| The first job that needs an account | "Create your saved passwords so the app can make an account on {site}" | Vault passphrase (show toggle, strength meter) + Gmail app password | Vault unlocked + IMAP/SMTP |
| The first email application | "This job asks you to apply by email" | Gmail already connected → confirm; else the Gmail card | — |
| A source that needs a key | Inline on the source row | The key | Vault |
| An unknown question | The answer card, grouped by question | The answer. LinKit remembers it for the same question; "Also save to my profile" for profile fields | Answer bank / profile |
| A privacy notice or legal declaration | "Accept privacy notices like this one?" | **This job only / Always / Ask me each time** | `acknowledge_*` |
| Notice period, relocation, demographics, personal details | A select or form | One-time "always" choice | Profile |
| LinkedIn posts | One quiet note in Settings, no checkbox | — | — |
| Google check on LinkedIn posts | Flag in Settings + "Solve Google check" (opens the app browser) | The user solves it | — |

Rule: a just-in-time card never blocks other jobs. Only that job waits. Park codes: `needs_vault`, `vault_locked`, `needs_email`; `retry-code` requeues all jobs waiting on one.

---

## 7. Information architecture

```
Home        next best action · funnel (numbers are links) · today's numbers · daily-search toggle · tasks
Jobs        all jobs, filters, job detail ("Why was this left out?") · reason chips · open jobs live in the URL
Needs you   [Approve jobs] [Finish applications]   ← Review + Action Center (one badge)
Activity    [Now] live events + screenshot view · [History] runs + report + export
Settings    Profile & CV · Jobs & places · Sources · Answers · Applying · Accounts & email · AI · Advanced
```
- `''` → Home. Home sends a new user to `/welcome`. A "Setup n/4" chip sits on Settings until done.
- Old routes (`/review`, `/actions`, `/live`, `/report`, `/vault`, `/answers`, `/setup`) redirect to the new tabs.
- Phone width: the status pill and the Needs-you count stay in the top bar; tap targets are 40 px; toasts sit at the bottom and never cover buttons.

### 7.1 Home: one place answers "what now?"

```
┌ Next ──────────────────────────────────────────────────────────┐
│ 14 possible matches are waiting for you.   [ Review 14 ]        │
└────────────────────────────────────────────────────────────────┘
Found 1,240 → passed filters 310 → strong 22 · possible 14 → applied 9 (practice)
Last search: today 09:00 · next: tomorrow 09:00   [✓] Search every day at [09:00]
Tasks: ☐ Ready to apply for real?   ☐ LibreOffice (optional)
```
Counts come from `/status` (`ready_to_apply`, `practiced`) and update right after approve, skip and answers.

---

## 8. Running and going live

### 8.1 Smart primary button (D9)

| State | Label |
|---|---|
| Setup not done | Finish setup (step n of 4) |
| No jobs yet | Find jobs |
| A run is going | Searching… n found · Stop (a cancelled run ends as "cancelled", resumable; the UI shows Stopping…) |
| Applications parked | Finish n applications |
| Possible matches waiting | Review n possible matches |
| Jobs ready (approved or strong) | **Apply to n jobs** (practice mode: "Apply to n jobs (practice)"), also offered as "Apply now" in the approve toast |
| Nothing queued | Find new jobs |

Activity buttons and run titles follow the chosen steps. "Start fresh" and the stage checkboxes are under Activity → Advanced.

### 8.2 Guided unlock for real applications (D10)

After the first practice run with a filled form, a Home task "Ready to apply for real?" opens a card (also in Settings → Applying):
1. Screenshots of practice forms (open in an in-app viewer) and a link to the tailored CV.
2. A checklist computed from **real state**, each item with its value and a fix link: CV ready, tailoring mode, open items, "confirm each" on.
3. "Turn on real applications" opens a named confirm: "Submit real applications from now on?" with "Each one is sent in your name and can't be taken back." and "You'll still confirm each application before it's sent" (or the opposite when "Submit without asking" is on). **Cancel is first.**
4. "Submit without asking" stays a separate Advanced switch.

The header badge changes from **Practice mode** to **Applying for real**.

### 8.3 AI usage limits

A usage limit pauses the run with one translated message and a reset date (`ai_usage_limit`), never a doubled vendor error or "failed". The UI offers "use another AI".

---

## 9. Vocabulary (EN and AR; the new Arabic terms still need a native check)

| Concept | Old | EN | AR |
|---|---|---|---|
| Dry run | Dry run | Practice mode | وضع التجربة |
| Live | Live | Applying for real | تقديم فعلي |
| Tier | high / mid / low | Strong / Possible / Weak match | تطابق قوي / محتمل / ضعيف |
| Action Center + Review | — | Needs you | بانتظارك |
| Run | Run | Search | بحث |
| Stage | Stage | hidden (Advanced only) | — |
| Vault | Vault | Saved passwords | كلمات المرور المحفوظة |
| Answer bank | Answer bank | Saved answers | الإجابات المحفوظة |
| Ghost job | Ghost job | Stale posting | إعلان قديم |
| Why a job is out | — | "Why was this left out?" / "Why is this here?" | — |
| Privacy | "Everything stays here" | "What leaves this computer" | — |

~~Locked facts / "Never changed in your CV"~~ is gone from the UI: protection is automatic (D24).
Code names (`dry run`, `tier`, `needs_user`…) stay. UI copy only: `i18n/en.ts` + `ar.ts`.

---

## 10. "Needs you"

- **Approve jobs**: card list, J/K/A/S/O/X keys with a `?` cheat sheet, bulk approve with a 10 s Undo, reason and missing skills on each card.
- **Finish applications**: setup cards (saved passwords, Gmail) above the jobs waiting on them; parked items **grouped by question** ("9 applications ask: …" → "Answer all 9"). Sensitive questions group only on exact wording. CAPTCHA, login and 2FA stay one per item.
- Each card: what happened · why · one primary fix button; everything else sits in a More menu (52b068e).
- Empty state: "Nothing needs you." with the notification toggle inline.

---

## 11. Learnability and memorability

1. **Source badges** on every derived value.
2. **Reason chips** on filtered and low jobs, "Why was this left out?" in the job detail. The reason links to its setting, with one-click "Allow this word" and "Remove from blocked companies" (Undo).
3. **Funnel numbers as links** on Home.
4. **"Changed" marks** in Advanced + a reset link.
5. **First-time hints**: one dismissible line per page (`localStorage`); "Show tips again" in Settings.
6. **Keyboard shortcuts** in Needs you.
7. **Same button names everywhere**, verbs first.
8. **The return path**: notifications say one thing to do and land on that tab.
9. **What leaves this computer**: one panel, linked from the welcome screens and the go-live card.

---

## 12. Roadmap

### Built

| Phase | What | Commit |
|---|---|---|
| UX1 | Inference layer, presets, per-job sponsorship | 2777e78 |
| UX2 | 4-screen first run | 4d96adc |
| UX3 | Autosaving Settings | da96a87 |
| UX4 | Home, Needs you, Activity, plain-word vocabulary | 986969a |
| UX5a / UX5 | Just-in-time park codes + batch answers / Needs you that clears fast | 3c9ae0c / 60eb327 |
| UX6a / UX6 | Presets, job reasons, go-live data / guided go-live, reason chips, hints | da5a346 / 6ee5dc3 |
| Docs | CLAUDE.md and handoff for phase 12 | b32a249 |
| Also | AI English-only; Arabic plurals; test fakes; cancelled-run fix; study kit; LinkedIn via Google | 947d891, 39a7e3f, 23f0b3a, 743a70b, c8b23aa, 9d033de |
| Round 2 | Backend: places, offline suggestions, FX, new answers | ec1d220 |
| Round 2 | Shared inputs (tags, places, phone), Profile & CV | ea22b5e |
| Round 2 | Jobs & places; first-run places with work rights | dd5e4d2 |
| Round 2 | Job sources and Answers | bc15cd3 |
| Round 2 | Applying limits, one browser setting, Advanced clean-up | a11af9f |
| UX7 fixes | Frontend: reasons that lead somewhere, phone width, Arabic | 92709c3 |
| UX7 fixes | Backend: AI limits pause, optional LibreOffice, real go-live checks | ba46591 |
| UX7 fixes | Frontend: apply path, LibreOffice choice, honest go-live and privacy | 717f827 |
| After UX7 | Headless Chrome client-hints fix | e576eb0 |
| After UX7 | LibreOffice one-click install points at the hosted bundle | dfb7c26 |
| U16 | "Company · platform" source names; structured AI check | 60b9c97 |
| U15–U17 | Go-live in Home's main card with CV red-line; plain words; visible apply runs; practice badge on welcome | d821983 |
| U17 | Per-job apply events (start, reason code, question count) | 93637ec |
| U18 | Needs-you cards with one main action; work rights per country; level tips; flags; PDF name; small items | 52b068e |

### Left

| Item | Notes |
|---|---|
| Study with real people | Use the kit in `docs/usability/` (5 people, Task 5 seven days later). Install LibreOffice (one click) and sign in to an AI with quota first |
| Merge the Outlook branch | `claude/outlook-oauth-898770`; needs an Azure client id |
| Native review of the Arabic SUS | and of the new Arabic terms (section 9) |
| Place picker Enter key | Built (46d5521) |
| Unverified | Real Gmail connect; local-model pick on a real server; Indeed country (U11) on a real Egypt place. The LibreOffice install is verified (real install from the release) |

---

## 13. CLAUDE.md edits

Done (b32a249 and later commits): §5.5 sponsorship per job, §5.7 Needs you, §6 vault just in time, §7 screens, §10 phase 12. Nothing pending.

---

## 14. Validation plan (no telemetry: moderated sessions only)

- **Who**: 5 people. 3 non-tech MENA job seekers (one Arabic-UI user), 2 developers. A fresh Windows machine, the app installed.
- **Tasks**: (1) install to first search; (2) why was a job left out; (3) answer a question 4 parked applications share; (4) turn on real applications; (5) **7 days later**, approve and apply without help.
- **Method**: think-aloud, 45 min, affinity map, impact/effort sort. Kit: `docs/usability/` (script, consent, SUS EN/AR, notes and results templates, sample CV, `scripts/seed_usability.py`).

| Metric | Target | Simulated round 1 (2026-11-01) |
|---|---|---|
| CV chosen to first search | ≤ 3 min | median 4:15 (not met) |
| Decisions before first search | ≤ 5 | median 6 (not met) |
| Task success, tasks 1–4 | ≥ 80 % | 19 of 20 = 95 % |
| Task 5 after 7 days | ≥ 4 of 5 | **0 of 5** before the fixes (not run after 7 days) |
| SUS | ≥ 75 | **mean 60** (non-tech 55, developers 67.5) |
| Derived CV fields correct | ≥ 90 % | 86.7 % on the sample |

**The round was simulated** (AI agents played five personas). It found 18 issues (U1–U18); the fixes in 92709c3, ba46591 and 717f827
cover U1–U14; d821983, 93637ec, 60b9c97 and 52b068e cover U15–U18 and the smaller items. It does **not** replace the study with real people. Full results and caveats: `docs/usability/simulated-round-1.md`.
Per D27 there are no more simulated rounds.

---

## 15. Still open

| # | Question | State |
|---|---|---|
| Q1 | Telegram channel lists for Gulf and non-tech MENA: who curates them? | The first MENA tech channels are in; the rest ship empty until you give a list |
| Q6 | Azure client id for Outlook | Needed before the Outlook branch can be merged and tested |
| Q7 | Native Arabic reviewer for the UI terms and the SUS | Not arranged |
| Q8 | Is the Indeed country bug (U11) real? | Fixed in ba46591 by mapping each jobspy key to one country; not re-checked on a real Egypt place |

Answered: Q2 internships count (D13); Q3 Outlook branch (D14); Q4 no power-user wizard (D15); Q5 LibreOffice bundle hosted (D31).

---

## 16. Execution status

Started 2026-10-29. An orchestrator planned and reviewed; Sonnet executors built; Haiku assistants searched and browser-tested.
Rules: one commit per phase on `main`; Arabic written for every new key; no new dependencies; ruff, mypy, pytest and `ng build` clean.

| Tasks | Phase | Status | Commit |
|---|---|---|---|
| T1.1–T1.4 | UX1 | done | 2777e78 |
| T2.1 | UX2 | done | 4d96adc |
| T3.1–T3.2 | UX3 | done | da96a87 |
| T4.1–T4.2 | UX4 | done | 986969a |
| T5.1 / T5.2 | UX5 | done | 3c9ae0c / 60eb327 |
| T6.1 | UX6 | done | da5a346 / 6ee5dc3 |
| T7.1 | CLAUDE.md, handoff | done | b32a249 |
| T7.2 | Browser E2E on a fresh install: 10 of 10 flows, 1813 tests, ruff, mypy, ng build clean | done | 743a70b (fix found) |
| Round 2 | Places, suggestions, FX, inputs, Settings rework | done | ec1d220 … a11af9f |
| UX7 | Study kit; simulated round; fixes | kit and fixes done, real study pending | c8b23aa, 92709c3, ba46591, 717f827 |
| UX7 follow-up | U15–U18 and the smaller items; LibreOffice hosted; headless fix | done | e576eb0, dfb7c26, 60b9c97, d821983, 93637ec, 52b068e, 46d5521 |
