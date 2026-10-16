# LinKit All

LinKit All is a job search tool that runs on your own computer. It finds jobs, ranks them
against your CV, tailors your CV for each job with small word-level edits, and fills in
the application forms for you. You watch and steer it from a web page that only your
computer can open.

You bring your own AI: a ChatGPT plan (Codex CLI), a Claude plan (Claude Code CLI), an API
key, or a local model such as Ollama or LM Studio.

!!! warning "Be careful with live applying"
    LinKit All starts in **dry-run mode**. It fills in forms and takes screenshots, but it
    never presses Submit. You have to turn on live applying yourself. Read
    [Applying](applying.md) before you do.

## What it does

1. **Finds jobs** from the company career pages and job sites you list. See [Sources](sources.md).
2. **Filters and ranks** them with free, local rules and a local embedding model. See [Matching](matching.md).
3. **Scores** the best ones with your AI, in batches, and sorts them into tiers.
4. **Tailors your CV** for the jobs it will apply to. It changes a few words and leaves the
   layout alone. See [Tailoring](tailoring.md).
5. **Applies** in a real Chrome window, including sites that need an account. See [Applying](applying.md).
6. **Asks you** whenever it should not guess. See [Action Center](action-center.md).
7. **Reports** what happened. See [Scheduling and reports](scheduling-reports.md).

## The pipeline

```text
Sources -> Discover -> Enrich -> Filter/Rank -> AI Score -> (Review) -> Tailor -> Apply -> Report
                                                                         Apply <-> Action Center
```

Every job has one state. It moves through these states, and each move is written to the
job's history:

```text
discovered -> enriched -> filtered_out | ranked -> scored
scored -> below_threshold (low) | awaiting_review (mid) | queued_apply (high, or approved by you)
queued_apply -> tailored -> applying -> needs_user -> applied | failed | skipped
```

- Each stage can be run on its own (`linkit run discover`, `linkit run rank`, and so on).
- Each stage can be stopped and started again. It carries on where it left off.
- Tailoring happens just before applying, never for a job that will not be applied to.

## Safety promises

These rules are built into the code, not just written down.

- **Your CV is never invented.** The AI may only suggest small patches. Patches that touch
  your locked facts, add skills you did not list, or change numbers, dates or contact
  details are rejected. See [Tailoring](tailoring.md).
- **The AI never answers sensitive questions.** Work authorization, visa and sponsorship,
  salary, gender, race, disability, veteran status, criminal record and legal statements
  are answered only from what you typed in, or sent to you. See [Action Center](action-center.md).
- **Dry run never submits.** In dry-run mode the Submit button is never clicked.
- **"Applied" needs proof.** A job is marked applied only when the site's confirmation page
  is seen (or you say you applied by hand). Otherwise it is failed or waiting for you.
- **CAPTCHAs are yours.** LinKit All never solves or bypasses a CAPTCHA. It stops and asks you.
- **Your data stays here.** Only the AI provider you choose sees your CV and job text.
  There is no telemetry. See [Privacy and security](privacy.md).
- **Polite scraping.** Careers pages and sitemaps are read only where `robots.txt` allows,
  with per-site rate limits. Bot challenges are never worked around. See [Sources](sources.md).

## Where to start

1. [Install](install.md) LinKit All and its helper tools.
2. Run `linkit` and follow the [setup wizard](setup.md).
3. Press **Find jobs now**, look at the results, then try a dry-run apply.
