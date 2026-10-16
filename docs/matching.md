# Matching

Thousands of jobs can arrive in one run. Matching cuts them down in three steps. The first two
are free and run on your computer. Only the survivors go to your AI.

```text
discovered -> enriched -> [1. hard rules] -> [2. local rank] -> [3. AI score] -> tiers
```

## 1. Hard rules

These are the **Filters** in the wizard (the `[filters]` section of `search.toml`). A job that
fails one is marked `filtered_out`, and the reason is saved in its history. Rules are checked
in this order, and the first failure wins.

| Rule | Behavior |
|---|---|
| `title_include` | The title must contain at least one of these words. Empty means any title. |
| `title_exclude` | The title must contain none of these words. |
| `remote` | `any`, `remote`, `hybrid` or `onsite`. If a posting does not say, it counts as on-site. |
| `locations` | The job's location (or work mode) must contain one of these. Empty means anywhere. |
| `seniority` | Taken from the title. Empty means any. |
| posted date | Older than `posted_within_days` (default 14) is dropped. |
| `salary_floor` | Yearly. Only checked when the posting states a salary. Hourly, daily, weekly and monthly pay is scaled to a year. |
| `company_blacklist` | Companies you never want. |

Seniority words are looked up in the title, in this order: intern or trainee; VP, chief or
executive titles; manager, head of or director; lead, staff, principal or architect; senior;
junior, entry or graduate. Any other title counts as `mid`.

**One job per company** (`one_per_company`, on by default). Only the best-ranked job at each
company moves on. A company that already has a job in your pipeline gets no second one.

## 2. Local rank

Each surviving job gets a rank (roughly 0 to 1), with no AI call:

```text
rank = 0.8 x similarity(CV, job) + 0.2 x skills overlap
```

- **Similarity** uses a small multilingual embedding model (about 220 MB, downloaded once). It
  reads both Arabic and English. Long texts are cut into chunks and averaged.
- **Skills overlap** is the share of the skills in your profile that the job mentions as whole
  words. If you listed no skills, only the similarity is used.

Jobs are then ordered by rank. Your CV text never leaves your computer in this step.

## 3. AI score

The best `ai_max_jobs` jobs by rank (default 300) go to your AI. Everything below that line
is marked `low` without spending any AI.

- Jobs are sent in **batches** of `batch_size` (default 15) in one call.
- The AI sees your CV (its first 6,000 characters), your title, location, work mode and
  seniority preferences, and a short summary of each job (the first 1,500 characters of the
  description).
- For each job it returns a **score from 1 to 10**, short reasons, missing skills and red flags.
  These show in the job's detail panel.

If your AI plan hits a usage limit, the run **pauses**. The jobs not yet scored stay ranked
and are scored the next time you start a run.

## Tiers

| Tier | Default score | What happens |
|---|---|---|
| **high** | 8 to 10 (`tier_high`) | Goes straight to the apply queue (`queued_apply`) |
| **mid** | 5 to 7 (`tier_mid`) | Waits in your **Review queue** (`awaiting_review`) |
| **low** | below 5, or not sent to the AI | Hidden (`below_threshold`) |

Change the two numbers in the wizard's **Filters** step.

### Review queue

Open **Review queue** in the menu. Mid jobs are listed on one tab, and low jobs on the other.
Select jobs and press **Approve** (they join the apply queue) or **Skip** (they are dropped).
You can also open a job and approve or skip it from its panel. This is also how you apply to a
low-tier job: approve it by hand.

## The `[matching]` settings

```toml
[matching]
ai_max_jobs = 300   # best locally-ranked jobs sent to the AI per run
tier_high = 8       # score 8-10: auto-apply
tier_mid = 5        # score 5-7: needs your approval; below: hidden
batch_size = 15     # jobs per AI call
```

`ai_max_jobs` is the main lever for AI cost. Lower it to use less of your plan.

## Running the steps by hand

```bash
linkit run discover
linkit run enrich
linkit run rank
linkit run score
linkit jobs --tier mid
```

See [Command line](cli.md).
