# Apply scorecard

Practice mode, 2026-11-11: 18 real job postings, forms filled and nothing submitted. The CV was
sent as uploaded.

This is a first, small sample: a made-up test profile with complete answers, Claude Haiku as the
AI, three jobs per source, no Lever job. It shows where applications stop, not a success rate to
quote.

| platform | tried | filled to the end | account needed | needs you | failed | skipped | median time |
|---|---|---|---|---|---|---|---|
| form agent | 12 | 0 (0%) | 3 | 9 | 0 | 0 | 6 s |
| ashby | 3 | 0 (0%) | 0 | 3 | 0 | 0 | 25 s |
| greenhouse | 3 | 1 (33%) | 0 | 2 | 0 | 0 | 18 s |

## Why the others stopped

| platform | result | reason | jobs |
|---|---|---|---|
| form agent | needs_user | apply_by_hand | 5 |
| ashby | needs_user | unknown_question | 3 |
| form agent | dry_run | dry_run_signup | 3 |
| form agent | needs_user | apply_in_browser | 2 |
| greenhouse | needs_user | unknown_question | 2 |
| form agent | needs_user | apply_in_browser_offsite | 1 |
| form agent | needs_user | unknown_question | 1 |

## What the reasons mean

- `unknown_question`: the form was read and filled, and 2 to 4 questions were left for the
  user. Most were yes/no questions about that one job (office days, remote work, message
  opt-ins) or a work-authorization question that depends on the job's country.
- `apply_by_hand`: the form agent could not find or finish the form on that site.
- `dry_run_signup`: the site wants an account first. Practice mode never creates one.
- `apply_in_browser`: LinkedIn. The app never drives it; the user applies in their own browser
  with the LinkIt Fill extension.

Made with `linkit apply-probe --per-source 3 --scorecard docs/scorecard.md`; this text and the
"account needed" column were added by hand after the run.
