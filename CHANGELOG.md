# Changelog

All notable changes to LinKit All. Dates are release dates.

## Unreleased

### Changed
- Remote control moved from Settings > Phone to a **Remote control** button on Home. It opens a
  popup that turns the tunnel on and shows the pairing QR code, with the paired phones below it.
- New `linkit rc`: runs LinKit All in the terminal with no browser tab and prints the pairing QR
  code there.
- On the phone, the bottom bar no longer has a Report tab (the report is on Home), and Settings
  is no longer shown.

### Fixed
- Jobs on the phone stayed empty with a large job list: the whole list (megabytes) had to come
  through the relay. The phone now gets the 200 best matches and searches the rest on the PC.

## 1.3.0 — 2026-11-28

### New
- On your phone: turn on Settings > Phone and scan the QR code with your phone. It opens the
  LinKit web app at https://linkit-all.github.io/app/ (Android and iPhone, no app store, no
  account). From there you can start and pause runs, approve jobs, answer Needs you questions and
  open an answer sheet to apply on the phone. The phone reaches your PC through an end-to-end
  encrypted iroh tunnel: your PC connects out, relays carry only encrypted data, and no port is
  opened. Off by default. A paired phone cannot read the vault, export data, change AI keys or turn
  on "submit without asking". Push alerts carry only a count.
- Docs: [On your phone](https://linkit-all.github.io/docs/phone/).

### Changed
- The website moved to https://linkit-all.github.io/ (docs at `/docs/`). Every page at the old
  address, silentco2.github.io/LinKit-All/, now sends you to the same page there.

## 1.2.0 — 2026-11-27

### New
- Free models: run LinKit on the free API tiers of Groq, Cloudflare Workers AI, Z.AI and
  OpenRouter (Settings > AI > Free models, or the first-run AI step). Add one or more keys and
  order them; when one reaches its limit or fails, the next one answers. The run pauses only when
  all of them are out. Each provider you add receives your CV and job texts; providers that may
  keep or train on them are marked.
- Each free provider card has a "How to get a key" guide.
- `linkit ai-check` tests each free provider on its own.
- Docs: [Free AI models](https://silentco2.github.io/LinKit-All/docs/free-ai/), with the limits,
  data terms and measured token use (one search a day fits in a single free tier).

### Fixed
- The API key option on the AI step now shows its key and model boxes, and keeps a saved key
  when you switch to another AI and back.
- Cloudflare answers are no longer cut off at 256 tokens.
- Groq gets smaller score batches (6 jobs) and low reasoning so it stays inside its per-minute
  token limit; a Groq JSON check failure is asked again.
- Password managers no longer autofill the API key boxes.

## 1.1.0 — 2026-11-22

### New
- Add a job by hand: paste links, paste the posting text, or upload it as a PDF (Jobs > Add a
  job). Jobs you add skip the hard rules; the trust check still runs.
- The AI score call now also reads work mode, location and salary when the posting leaves them
  out of its fields. Each is kept only when a quote from the posting backs it, and one that breaks
  your rules makes the job a weak match.
- New sources: Gradcracker, Jobindex and Naukri; place suggestions for the UK, Denmark and India.
- Visa sponsors: in your visa countries, jobs at employers on the official sponsor lists (UK,
  Netherlands, US H-1B, Canada LMIA) get a label and a small ranking boost. The lists refresh at
  most weekly and send no personal data.
- Source health: each source shows whether it worked in recent runs; `linkit source-check`
  tests them on demand.
- Backups: a daily copy of the database (newest 7 kept, folder of your choice), plus
  `linkit backup` and `linkit restore`.
- Needs you: "Rewrite with AI" and "Draft with AI" on free-text answers and the email body, with
  an optional wish and Undo. Never offered for sensitive questions.
- "You applied here before" note on the job page and when you add a job.
- Ctrl/Cmd+K quick jump to jobs and pages; a place radius for nearby cities.
- Report a problem or suggest a feature from the app's footer as a GitHub issue you submit
  yourself; it is pre-filled with the version, system and AI only.

### Changed
- A retry after you change your CV tailors the CV again instead of reusing the old version.
- AI-written prose is checked for stock phrases and rewritten by rules.
- The browser extension is now spelled "LinKit Fill", matching LinKit All.
- New README, issue forms (Bug, Site not supported, Feature) and comparison pages for AIHawk
  and ApplyPilot.

## 1.0.0 — 2026-11-19

The first public release.

### Find jobs
- Public job APIs of Greenhouse, Lever, Ashby, Workday and 100+ other applicant tracking
  systems, plus LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google and Bayt through
  python-jobspy, regional boards (Wuzzuf, Forasna and more), any company careers page, and
  Telegram channels.
- Opt-in LinkedIn hiring posts, found through Google and read from their public pages, without
  a LinkedIn account.
- Duplicates removed by address, by title + company + location, and by fuzzy matching.
- 52 new opt-in sources (295 in all) and a list of 143 suggested company boards.
- A source that hangs no longer freezes a search.
- `linkit find-board` and `linkit seed-boards` find and add company boards.

### Rank and check
- Hard rules (titles, places, remote mode, level, date, salary floor, blocked companies, one
  application per company), then a free local ranking with a multilingual embedding model.
- An offline trust check scores scams and ghost jobs in English and Arabic.
- The AI scores only the jobs that survive, 10 to 20 per call, and sorts them into Strong,
  Possible and Weak matches.
- Jobs that ask for more years than your profile has, or use a dealbreaker phrase, are dropped
  or labelled.
- `linkit filter-audit` and `linkit why-missed` show why a job was filtered out or missed.

### Tailor the CV
- Small word-level edits to Word, LaTeX, OpenDocument and PDF CVs, never a rewrite. Edits that
  touch locked facts, add unlisted skills, change numbers or dates, or grow the text too much
  are refused.
- The PDF must keep the same page count and look; otherwise every edit is rolled back.
- Tailoring is optional: the CV can go out exactly as uploaded.

### Apply
- Form handlers for Greenhouse, Lever and Ashby; a generic AI form agent for every other site.
- Account sign-up with a generated password kept in an encrypted local vault, email codes read
  over IMAP (Gmail, Yahoo) or Microsoft Graph (Outlook), and optional Sign in with Google.
- Sensitive questions (work rights, visa, salary, demographics, disability, veteran status,
  criminal record) are never answered by the AI: from your profile, or they wait for you.
- LinkedIn, Indeed and Glassdoor are never driven: the LinKit Fill browser extension fills them
  in your own browser while you press Next and Submit.
- Applications by email, with a short cover email and daily limits.
- Practice mode by default: forms are filled and screenshotted, never submitted.
- A knock-out pre-scan parks a form that would reject you (years, degree, no sponsorship, pay
  ceiling) before anything is typed. "Apply anyway" is your call.
- Age and health questions are answered from your profile (date of birth, disability answer).
  Empty fields still ask you.
- On 115 real postings in Practice mode, 67 of the 70 jobs the app may finish alone went as far
  as Practice mode allows (96%). See the [scorecard](https://silentco2.github.io/LinKit-All/scorecard/).

### After applying
- Each applied job can carry an outcome: no reply, rejected, interview, offer, hired or
  declined.
- Opt-in "Read employer replies": recent inbox mail is read by rules on your computer to set
  outcomes. It is never sent to the AI or logged.
- One follow-up email after `followup_days` days without a reply. It is sent by itself only when
  Applying for real with "submit without asking"; otherwise the job notes it is due.

### Privacy
- Sensitive answers are removed from page text before it goes to the AI; the privacy page says
  what can still get through.
- With a local model, LiteLLM needs no internet: its tokenizer file ships with the app and its
  price list is no longer downloaded.

### The app
- A local web page in English and Arabic: first-run setup, Home with the live run, Jobs, Needs
  you, Settings, reports with CSV/PDF export, and a scheduler.
- AI from a ChatGPT plan (Codex CLI), a Claude plan (Claude Code), an API key through LiteLLM,
  or a local model (Ollama, LM Studio).
- `linkit bench` measures finding, ranking, the tailoring guard and form filling on a built-in
  fake job board; CI runs it on Windows, macOS and Linux.
- `linkit apply-probe` tries real postings in Practice mode and writes a per-platform scorecard.
