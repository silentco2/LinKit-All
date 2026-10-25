# Job trust check

LinKit All checks every job for two different problems before any AI is used. The check runs
on your computer, offline, and costs no AI calls.

## The two scores

Each job gets two scores from 0 to 100. A higher score means more risk.

| Score | What it looks for |
| --- | --- |
| **Scam risk** | Fees or deposits, moving the chat to Telegram or WhatsApp, requests to move money, buy things or send ID documents, crypto, hiring without an interview, pay that is too good to be true, a free email address as the contact, and an apply link on a site that does not match the company. English and Arabic, including text written to dodge filters (odd characters, spacing, letter swaps). |
| **Ghost-job risk** | A real company with an opening that is probably not being filled: an old posting date, the same job seen again in many runs, repeated reposts, and vague or evergreen wording ("always hiring", "talent pool", no concrete duties). |

Postings on a known hiring system (Greenhouse, Lever, Ashby and similar) count in the job's
favour for the scam score.

## Bands

| Band | Scam risk | Ghost-job risk |
| --- | --- | --- |
| Low | below 35 | below 35 |
| Medium | 35 to 64 | 35 to 49 |
| High | 65 and up | 50 and up |

The bands follow the two thresholds in Setup (default 65 and 50). The thresholds are a first
guess and may need tuning on real runs.

## What happens to a flagged job

- **Scam at or above the scam threshold:** the job is filtered out with a reason. It is never
  scored, tailored or applied to.
- **Ghost at or above the ghost threshold:** the job goes to the `low` tier, so it is hidden and
  not auto-applied (unless you opted in to applying to low jobs). If you turn on *Also filter out
  ghost jobs above the threshold*, it is filtered out instead.
- **AI opinion:** the normal AI score also returns a verdict (`ok`, `suspicious`, `scam`) and
  flags, with no extra call. The AI can raise a job's scam risk but never lowers or clears it.
- **Closed postings:** before tailoring, a job that is no longer open on Greenhouse, Lever or
  Ashby is skipped.

The jobs table shows one badge per job (for example "Likely scam" or "Possibly stale"). Open the
job to see the signals behind the scores, in your language.

## Not a scam / Report

In a job's details:

- **Not a scam** restores a job that was filtered out as a scam and adds its company to your
  not-a-scam list, so that company skips the scam check from then on.
- **Report as scam** adds the company to your never-apply list and skips the job. You are asked
  to confirm first.

## Settings

In Setup, under *Job trust check*:

- **Check every job** switches the check on or off (on by default).
- **Scam threshold** (default 65) and **Ghost threshold** (default 50).
- **Also filter out ghost jobs above the threshold** (off by default).
- **Not-a-scam companies**, one per line.
- **Filter out ghost jobs now** applies the ghost threshold to jobs you already have. Jobs that
  were already scored are skipped, and this cannot be undone automatically.

!!! warning
    The scores are signals, not proof. Check a flagged job yourself when it matters, and
    never pay a fee or send ID documents to apply for a job.
