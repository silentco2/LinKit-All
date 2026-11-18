# Show HN

**Title** (80 characters at most):

Show HN: LinKit All – open-source job search and auto-apply that runs locally

**URL:** https://github.com/silentco2/LinKit-All

**First comment** (post it yourself right after submitting):

Hi HN. I built LinKit All because applying for jobs had turned into filling in the same forms
hundreds of times, and the tools that automate it either sent my CV to their servers or let an
AI make things up on it.

It runs on your own computer. It pulls jobs from the public APIs of Greenhouse, Lever, Ashby,
Workday and about 100 other applicant tracking systems, plus LinkedIn and Indeed through JobSpy
and any careers page. It ranks them against your CV with a local embedding model (no AI calls),
then has your AI score the best ones in batches.

You bring the AI: a ChatGPT or Claude plan through their CLIs, an API key, or Ollama/LM Studio.

A few rules are enforced in code, not prompts:

- CV tailoring is a patch list of small word edits, never a rewrite. A patch is refused if it
  touches a locked fact (employer, title, date, degree), adds a skill you did not list, changes
  a number, or grows the text too much. The PDF must keep the same page count and look, or
  every patch is rolled back.
- Sensitive questions (visa, salary, demographics, disability, criminal record) never go to
  the AI. They come from your profile or wait for you.
- It starts in Practice mode, which never presses Submit. LinkedIn, Indeed and Glassdoor are
  never driven by the app; a browser extension fills them while you click.
- No telemetry. Passwords for site accounts live in an AES-GCM vault on your disk.

Honest limits: only Greenhouse, Lever and Ashby have dedicated form handlers. Everything else
goes through a generic AI form agent. In the latest scorecard run (115 real postings, Practice
mode, a made-up profile, nothing submitted) it was tried on 55: 11 were filled to the end, 22
stopped at a sign-up page and 21 were left for the user (12 questions, 6 on sites it never
drives, 3 it could not finish). Across all sites, 67 of the 70 jobs the
app may finish alone went as far as Practice mode allows; 39 waiting for the user and 6
jobs on sites the app never drives are not counted. The numbers are in the README, along with a benchmark on a fake job board you can run yourself
with `linkit bench`.

Python (FastAPI, SQLite, Playwright attached to your installed Chrome over CDP) and an Angular
front end. AGPL-3.0. English and Arabic UI. I would love feedback, especially on the form agent
and on sites it should handle better.
