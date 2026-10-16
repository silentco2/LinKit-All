# Scheduling and reports

## Live run

Open **Live run** to start and watch a run.

- Tick the **stages** you want: *Find jobs* (discover), *Read descriptions* (enrich),
  *Filter and rank*, *AI scoring* and *Apply*. By default all five run, in that order.
- Tick **Start a new run** for a fresh run. Otherwise an unfinished run carries on.
- **Stop** cancels the run. Work already saved is kept.
- The **Activity** list streams what is happening, and each stage shows a short summary.
- Only one run goes at a time.

If your AI plan hits a usage limit, the run is **paused**, with the reason shown. Start it
again later and it continues with the jobs not yet scored.

## Scheduled runs

Under **Schedule** on the Live run page you can run LinKit All automatically.

| Setting | Meaning |
|---|---|
| Run automatically | Turns the schedule on. Off by default. |
| Days | Which days of the week. Default is every day. |
| Times | Up to 6 times a day, in your **local time**, as `HH:MM`. Default `09:00`. |
| Start a new run each time | On by default. Off resumes an unfinished run instead. |

The page shows the next times it will run. The same schedule can be set in
`search.toml`:

```toml
[schedule]
enabled = true
days = [0, 1, 2, 3, 4]   # 0 = Monday ... 6 = Sunday
times = ["09:00", "18:00"]
new_run = true
```

Things to know:

- **LinKit All must be running** at that time. It does not run in the background when closed.
  Start it with `linkit` and leave the window open. A run missed by less than an hour (for
  example because the app was just starting) still fires.
- A scheduled run does **all five stages**, with the same settings as a manual one. That
  means it is a **dry run unless live applying is on**, and the same caps and
  confirmation rules apply. In live mode with confirmation on, items wait in the
  [Action Center](action-center.md) for your click.
- If a run is already going, the scheduled one is skipped. It is not queued.
- The schedule is saved in your local database, and survives restarts.

### Desktop notifications

Tick **Desktop notifications** at the bottom of the left menu. Your browser asks for
permission. Then you get an alert when a run finishes, pauses or fails, and when new
items appear in the Action Center. These are browser notifications, so they need the LinKit All
page to be open in a tab.

## Reports

Open **Report** for the numbers. Choose **All runs** or one run at the top.

| Section | Shows |
|---|---|
| **Funnel** | Found, passed filters, AI scored, queued to apply, applied |
| **AI tiers** | How many jobs landed in high, mid and low |
| **Applications over time** | Applied, failed, needs you and skipped per day (last 90 days) |
| **By platform** | Counts per source and per ATS |
| **By career page (company)** | Counts per company, biggest first (top 100) |
| **By source** | Jobs per source, split by state |
| **Runs** and **Outcomes per run** | Each run's stats |

Use **Export CSV** or **Export PDF** to save the report. The exports contain job details
only (title, company, source, state, score, tier, dates, link). They never contain your CV
text, answers, passwords or emails. Spreadsheet-unsafe titles that start with `=`, `+`, `-`
or `@` are escaped.

On the command line, `linkit status` prints job counts by state and tier, and
`linkit jobs` lists the best jobs. See [Command line](cli.md).
