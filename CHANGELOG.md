# Changelog

All notable changes to LinKit All. Dates are release dates.

## 1.0.0 — unreleased

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
  are refused, and an AI claim check catches invented claims in other words.
- The PDF must keep the same page count and look; otherwise every edit is rolled back.
- Tailoring is optional: the CV can go out exactly as uploaded.

### Apply
- Form handlers for Greenhouse, Lever and Ashby; a generic AI form agent for every other site.
- Account sign-up with a generated password kept in an encrypted local vault, email codes read
  over IMAP (Gmail, Yahoo) or Microsoft Graph (Outlook), and optional Sign in with Google.
- Sensitive questions (work rights, visa, salary, demographics, disability, veteran status,
  criminal record) are never answered by the AI: from your profile, or they wait for you.
- LinkedIn, Indeed and Glassdoor are never driven: the LinkIt Fill browser extension fills them
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
