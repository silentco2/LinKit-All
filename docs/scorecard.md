---
title: "Apply scorecard: how far real applications get"
description: "Practice-mode results on real job postings per platform: how many applications LinKit All carried as far as practice mode goes and why the others stopped. Nothing submitted."
---

# Apply scorecard

Practice mode, 2026-11-13: 30 real job postings, five per source (Bayt, Greenhouse, Ashby,
LinkedIn, Indeed, Wuzzuf). Forms were filled and nothing was submitted. The CV was sent as
uploaded.

This is a small sample: a made-up test profile, Claude Haiku as the AI and no Lever job. It shows
where applications stop, not a success rate to quote.

**Passed** means the app went as far as practice mode allows:

- it filled the form to the last step, or
- it reached a sign-up form (practice mode never creates accounts; in real mode the app signs up,
  checks the email and goes on), or
- it found the ad closed (the job goes to the trash, hidden but kept so later searches skip it).

| platform | tried | passed | filled to the end | reached sign-up | ad closed | needs you | failed | skipped | median time |
|---|---|---|---|---|---|---|---|---|---|
| form agent | 20 | 13 (65%) | 0 | 10 | 3 | 7 | 0 | 0 | 25 s |
| ashby | 5 | 0 (0%) | 0 | 0 | 0 | 4 | 1 | 0 | 15 s |
| greenhouse | 5 | 1 (20%) | 1 | 0 | 0 | 4 | 0 | 0 | 21 s |

In all, 14 of 30 passed (47%). On 2026-11-11 it was 4 of 18 (22%).

## Why the others stopped

| platform | result | reason | jobs |
|---|---|---|---|
| form agent | dry_run | dry_run_signup | 10 |
| ashby | needs_user | unknown_question | 4 |
| greenhouse | needs_user | unknown_question | 4 |
| form agent | needs_user | apply_in_browser | 4 |
| form agent | skipped | posting_gone | 3 |
| form agent | needs_user | apply_in_browser_offsite | 1 |
| form agent | needs_user | apply_by_hand | 1 |
| form agent | needs_user | validation_error | 1 |
| ashby | failed | apply_crashed | 1 |

## What the reasons mean

- `unknown_question`: the form was filled, and 1 or 2 questions were left for the user. The AI
  answers anything it can work out from the CV, the profile and the job, and makes a reasonable
  choice on low-stakes questions. It leaves a question for the user only when it cannot work out
  the answer and the answer matters. The ones left were: a weekend shift each week, five
  on-site days in Maryland, which countries you would work in (the profile's country was not an
  option), remote or office for one role, and consent to recorded interviews.
- `apply_in_browser`: LinkedIn. The app never drives it; the user applies in their own browser
  with the LinkIt Fill extension.
- `apply_by_hand`, `validation_error`: the form agent could not finish the form on that site.
- `apply_crashed`: the site closed the connection while the page was loading.

Made with `linkit apply-probe --per-source 5 --scorecard build/scorecard-new.md`, then copied
here; this text was added by hand. Questions were checked again after giving the AI the
profile's remote preference.
