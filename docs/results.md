---
title: "Results and limits: how well LinKit All works"
description: "Benchmark results for LinKit All on 10,000 fake jobs, the CV tailoring guard, real postings in Practice mode, and the known limits."
---

# Results and limits

## How well does it work

A built-in fake job board generates made-up jobs whose right answers are known: which are duplicates, scams, ghost jobs, relevant, or invented CV edits. The people who wrote the code also wrote this test, so these numbers show that the pieces behave as designed. They are not real-world accuracy. To reproduce them, run `uv run linkit bench`. The form-filling rows need `uv run linkit bench --apply 9`, and the tailoring row with a real model needs `--provider claude_cli --model haiku` (or any provider and model you have). The tailoring figures below came from a run with `--jobs 100`. The figures are from a run on 2026-11-11 and can shift as the code and the fake jobs change.

10,000 fake jobs, a scripted stand-in for the AI, the real local embedding model:

| What was measured | Result |
|---|---|
| Duplicate jobs found (800 planted) | 800 found, 0 wrong |
| Scam jobs found (268 planted) | 249 found, 0 false alarms, 92.9% caught (19 missed) |
| Ghost jobs found | 274 found, 0 wrong, 0 missed |
| Ranking: how many of the top 10 and top 50 were relevant | 100% and 100% |
| Fake application forms (9: simple, two-page, sensitive) | 9 of 9 ended as expected: 6 filled in Practice mode, 3 sensitive-question forms waited for the user. 18 of 18 fields right, CV attached 3 of 3, 3 of 3 trap fields left empty, nothing sensitive sent to the AI |
| Speed | 110 seconds for 10,000 jobs (find, enrich, rank) on one machine |

CV tailoring guard, rules only (no AI reads the edits). The test planted 25 edits that we wrote for it: 6 honest and 19 that must be refused. Of those 19, 15 invent or change a fact (a changed employer, date, metric or email, an inflated title, an unlisted tool, a bigger role) and 4 break a formatting rule (Arabic text, a line break, text that is not in the CV, a segment grown far past its length). 17 of the 19 were refused and all 6 honest edits accepted. The 2 that got through were a tool the rules do not know and a bigger role said in other words. This is a small set of cases, not a guarantee that invented edits never get through.

Real sites: `uv run linkit apply-probe` tries real postings in Practice mode. The [scorecard](scorecard.md) covers 115 real postings run in Practice mode with a made-up test profile. Nothing was submitted. Of the 70 jobs the app may finish on its own, 67 (96%) went as far as Practice mode allows: the form filled to the last step, a sign-up page reached, or the ad found closed. Not counted: 39 jobs left waiting for an answer or a decision only you can give, and 6 jobs on sites the app never drives (such as LinkedIn), which you apply to in your own browser. It is a small sample, not a success rate.

## Limits

- Only Greenhouse, Lever and Ashby have dedicated form handlers. Every other site (Workday, iCIMS, Taleo and the rest) goes through a generic AI form agent. In the latest scorecard run it was tried on 55 postings: 11 were filled to the end, 22 stopped at a sign-up page (Practice mode never creates an account), 1 ad was closed, and 21 were left for you: 12 with questions only you can answer, 6 on sites the app never drives, and 3 it could not finish.
- LinkedIn, Indeed and Glassdoor are never driven by the app. The job waits and you apply in your own browser, where the LinKit Fill extension fills each step.
- Practice mode is the default. Real submitting (Applying for real) has so far been tried only in a few applications the maintainer watched by hand, and the automated tests run in Practice mode only. Watch your first run.
- CAPTCHAs are never solved. The job waits for you.
- The one-click LibreOffice install is Windows 64-bit only. On macOS and Linux, install LibreOffice yourself.
- macOS and Linux run the unit tests and the benchmark in CI on every change; the full install has been checked by hand on Windows only.
- AI use counts against your own plan limits or API key. When a limit is hit, the run pauses.
- Small local models may score and tailor less well.
