---
title: "Apply scorecard: how far real applications get"
description: "Practice-mode results on 115 real job postings: how far LinKit All got, why the rest stopped and where the time goes. Nothing was submitted."
---

# Apply scorecard

Practice mode, 2026-11-18: 115 real job postings from a fresh search (Indeed 40, Ashby 30,
Greenhouse 25, Lever 5, Bayt 5, Wuzzuf 5, LinkedIn 5). Forms were filled and nothing was
submitted. The CV was sent as uploaded. A made-up test profile, Claude Haiku as the AI.

**Passed** means the app went as far as practice mode allows:

- it filled the form to the last step, or
- it reached a sign-up form (practice mode never creates accounts; in real mode the app signs up,
  checks the email and goes on), or
- it found the ad closed (the job goes to the trash, hidden but kept so later searches skip it).

**Pass rate: 67 of 70 (96%)** of the jobs the app may finish on its own. Not counted, but listed
below: 6 jobs on sites the app never drives, such as LinkedIn (you apply in your own browser) and 39 that wait for an answer or a
decision only you can give.

10 of the 67 are ads an earlier run of the same sample already found closed; they stay in the
trash and were not opened again. Without them: 57 of 60 (95%).

| platform | tried | passed | filled to the end | reached sign-up | ad closed | needs you | failed | skipped | median time |
|---|---|---|---|---|---|---|---|---|---|
| form agent | 55 | 34 (62%) | 11 | 22 | 1 | 21 | 0 | 0 | 13 s |
| ashby | 30 | 16 (53%) | 10 | 0 | 6 | 14 | 0 | 0 | 21 s |
| greenhouse | 25 | 12 (48%) | 9 | 0 | 3 | 13 | 0 | 0 | 7 s |
| lever | 5 | 5 (100%) | 5 | 0 | 0 | 0 | 0 | 0 | 18 s |

The same 115 jobs, run after each round of fixes:

| run | pass rate | median per job |
|---|---|---|
| 2026-11-14, before the fixes | 36 of 58 (62%) | 18 s |
| 2026-11-17 | 56 of 69 (81%) | 18 s |
| 2026-11-18, first | 64 of 71 (90%) | 13 s |
| 2026-11-18, second | 67 of 70 (96%) | 14 s |

## Why the others stopped

| platform | result | reason | jobs |
|---|---|---|---|
| form agent | dry_run | dry_run_signup | 22 |
| ashby | needs_user | unknown_question | 14 |
| greenhouse | needs_user | unknown_question | 12 |
| form agent | needs_user | unknown_question | 12 |
| form agent | needs_user | apply_in_browser | 5 |
| ashby | skipped | posting_gone | 5 |
| greenhouse | skipped | job_closed | 3 |
| form agent | needs_user | apply_by_hand | 3 |
| ashby | skipped | job_closed | 1 |
| form agent | needs_user | apply_in_browser_offsite | 1 |
| form agent | skipped | posting_gone | 1 |
| greenhouse | needs_user | knockout | 1 |

## What the reasons mean

- `unknown_question`: the form was filled, and 1 to 10 questions were left for you. The AI
  answers anything it can work out from the CV, the profile and the job. What was left:
  - personal questions the test profile leaves empty: age ("over 18?"), date of birth, gender,
    marital status, military status, health, work authorization. The app answers these from your
    profile when you fill them in (age from your date of birth, health from your disability
    answer), never from a guess;
  - legal ones: employment agreements or post-employment restrictions, consent to recorded
    interviews;
  - work conditions: office days, hybrid work, US hours, on-call, which countries you would work in;
  - things the test profile does not have: a GitHub link, a portfolio, a story for "tell us about
    a time you…", the salary currency;
  - a CAPTCHA.
- `knockout`: the form would reject you (it asks for 9 years; the profile says 8). "Apply anyway"
  is your call.
- `apply_in_browser`: LinkedIn. The app never drives it; you apply in your own browser with the
  LinkIt Fill extension.
- `apply_by_hand`: the form agent could not go on. FlairsTech's page after Register, an Orange
  ad with no Apply button, and a softlock.net Apply that does nothing.

## Where the time goes

Median 14 s per job, slowest 62 s. A step's time leaves out the steps inside it, so the shares
add up to 100%. "other" is time outside any named step. The probe keeps every job's steps in
`job.data["timings"]`, and its report lists each job's three slowest steps with the reason.

| step | jobs | median per job | slowest | share of all time | why the slow ones took long |
|---|---|---|---|---|---|
| wait for page | 105 | 2.8 s | 30 s | 41% | the page or form never went quiet; the wait stops after 5 s (35 jobs) |
| fill form | 47 | 5.2 s | 16 s | 15% | a 0.2-0.7 s human pause after each answer (19 jobs) |
| load page | 105 | 0.9 s | 36 s | 11% | slow sites: wuzzuf.net, apply.workable.com |
| AI FieldMap | 16 | 6.4 s | 11 s | 6% | one Claude CLI call per new page |
| other | 111 | 0.5 s | 5 s | 5% | |
| answer questions | 73 | 0.8 s | 4 s | 4% | many questions on one page |
| AI Drafts | 13 | 5.8 s | 8 s | 4% | one Claude CLI call for the questions the rules cannot answer |
| check posting | 115 | 0.2 s | 18 s | 3% | |
| screenshot | 100 | 0.4 s | 2 s | 3% | |
| press button | 24 | 3.1 s | 4 s | 3% | |
| prepare CV | 111 | 0.2 s | 2 s | 2% | |
| read page | 100 | 0.1 s | 3 s | 1% | |
| open browser | 105 | 0.1 s | 14 s | 1% | |
| wait for site | 23 | 0.2 s | 15 s | 1% | the site said it was still uploading |
| wait for redirect | 24 | 0.0 s | 20 s | 1% | Apply changed nothing for 20 s (1 job) |
| account | 51 | 0.0 s | 0 s | 0% | |

Where to look next for speed: "wait for page" is the largest share, and most of it is pages that
keep loading trackers or chat widgets after the form is ready. AI time dropped once answers were
saved and reused (AI Drafts went from 46 jobs to 13).

Made with `linkit apply-probe --job … --provider claude_cli --model haiku --scorecard …` on the
same 115 jobs each run, then copied here; this text was added by hand.
