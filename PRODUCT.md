# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: job seekers who are tired of filling in the same application forms and can paste one install command into a terminal. They run the app on their own Windows, macOS or Linux computer and watch it from a local web page. Many apply in English; a meaningful share are Arabic speakers applying in Egypt and the Gulf (Wuzzuf, Forasna, Bayt, Naukrigulf).

Secondary: developers and open-source contributors, reached through the GitHub repo and the Development docs.

## Product Purpose

LinKit All is a free, open-source (AGPL-3.0) app that runs on the user's own computer. It finds jobs on 295 sources (public ATS APIs such as Greenhouse, Lever, Ashby and Workday, job boards through JobSpy, regional boards, any careers page, LinkedIn hiring posts, Telegram channels), ranks them against the user's CV, tailors the CV per job with minimal word-level edits that keep the layout, and fills in applications. Success: more real applications sent with less typing, and none the user would be embarrassed by.

## Positioning

- Runs locally with no account and no telemetry; only the AI provider the user picks sees CV and job text.
- Bring your own AI: ChatGPT plan via Codex CLI, Claude plan via Claude Code CLI, API keys, or local models (Ollama, LM Studio).
- Never invents CV content: locked facts, rule-based patch checks, numbers/dates/contacts auto-locked.
- Never lets the AI answer sensitive questions (work authorization, visa, salary, EEO, disability, veteran, criminal record); those come from the profile or wait for the user.
- Practice mode by default: fills forms, never presses Submit. "Applied" needs proof (confirmation page or email).
- Ban-risk sites (LinkedIn, Indeed, Glassdoor) are never driven; the LinkIt Fill browser extension fills them in the user's own browser while the user presses Submit.

## Operating Context

Install with `uv tool install linkit-all` (PyPI 1.0.0, released 2026-11-19), run `linkit`, follow a four-step first-run wizard (CV, AI, check what was found, what jobs). Home shows the run as step cards with a live screenshot view; "Needs you" collects questions, confirmations, CAPTCHAs and sign-ins. Needs LibreOffice (bundled portable build for Windows) and an installed Chrome, Edge or Brave.

## Capabilities and Constraints

- Shipped: discovery on 295 sources; offline scam and ghost-job trust check (EN + AR); local embedding rank; AI scoring in batches with Strong/Possible/Weak tiers; DOCX, LaTeX, ODT and PDF CV tailoring with page-count and visual-diff verification; Greenhouse, Lever and Ashby handlers plus a generic AI form agent; account sign-up with an encrypted vault and email-code verification (Gmail, Yahoo, Outlook); email applications; knock-out pre-scan; outcomes, follow-ups and reply reading; scheduler; reports with CSV/PDF export; Arabic UI.
- Coming soon (approved to show publicly): phone companion (installable PWA over the user's own private network: run controls, approvals, answer sheet, push alerts with no personal text); freelance Gigs workspace (finds and scores gigs on Upwork, Freelancer.com, Mostaql, Khamsat, Ureed and Bahr, drafts proposals; the user sends them).
- Not to be shown as coming: free AI gateway, macOS/Linux LibreOffice bundles.
- UI words: Practice mode, Applying for real, Strong/Possible/Weak match, Needs you, Search.

## Brand Commitments

- Name "LinKit All" (capital K), package `linkit-all`, command `linkit`. Browser extension "LinkIt Fill".
- The app's look, binding for the website too: "the application desk". Paper sheets on a desk, folder tabs for counts and trays, a rubber stamp for outcomes only. Tokens live in `frontend/src/styles.css`. IBM Plex Sans + IBM Plex Sans Arabic, bundled, never loaded from a web font service.
- Voice: plain, calm, honest about limits; no hype.

## Evidence on Hand

- `docs/assets/demo.gif`: 30-second demo recorded from the bundled fake job board (no real data).
- `docs/assets/social.png`: social preview card.
- `docs/scorecard.md`: practice-mode results on 115 real postings.
- `README.md`: bench numbers (rules-only tailoring guard refuses 17 of 19 invented edits, accepts 6 of 6 honest ones).
- No testimonials, users, press or download counts exist yet; never invent them.

## Product Principles

1. The user's data and name stay theirs: local, no telemetry, nothing sent without a reason.
2. Never guess where a wrong answer costs the user: ask instead.
3. Honest numbers or none.
4. Do the typing, leave the decisions.

## Accessibility & Inclusion

English and Arabic (right-to-left) in the app. Phone-width layouts with 40px touch targets. Respect reduced motion.
