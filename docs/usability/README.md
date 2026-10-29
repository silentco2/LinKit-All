# LinKit All usability study kit (UX7)

This kit helps you run five short, friendly sessions and turn what you see into a list of fixes.
It follows section 14 of `ux-plan.md`. No telemetry is involved: you watch people use the app, and you take notes.

## Purpose

We want to know if a new person can:

1. get from a fresh install to the first search quickly (target: 3 minutes or less from CV upload);
2. understand why a job was filtered;
3. answer one question that blocks several applications;
4. understand what "Applying for real" means before turning it on;
5. come back 7 days later and carry on without help.

We are testing the app, not the person.

## Who to recruit (5 people)

| # | Who | Why |
|---|---|---|
| P1 | Non-tech job seeker from the MENA region | Main audience |
| P2 | Non-tech job seeker from the MENA region | Main audience |
| P3 | Non-tech job seeker from the MENA region, **uses the Arabic UI** | Checks Arabic copy and right-to-left layout |
| P4 | Developer | Checks the advanced paths and the wording of technical terms |
| P5 | Developer | Same |

Non-tech means: comfortable with Word and a browser, has never used a command line, has applied for jobs online in the last year.
Do not recruit people who have seen the app before. Do not recruit friends who will be too polite to say it is confusing. Tell everyone the session takes 45 minutes, plus a 15-minute follow-up 7 days later.

## Files in this kit

| File | Use |
|---|---|
| `script.md` / `script.ar.md` | What you say, task by task (English and Arabic) |
| `consent.md` / `consent.ar.md` | Hand to the participant before you start |
| `sus.md` / `sus.ar.md` | Questionnaire at the end, plus scoring |
| `sample-cv.md` | A fictional CV (EN and AR) for people who do not want to use their own |
| `notes-template.md` | One copy per participant |
| `results-template.md` | The synthesis, filled in after all five sessions |

## Setup checklist (do this before each session)

Use a clean state every time. A leftover profile from the last person ruins the first-run test.

- [ ] A **fresh Windows machine**, or the same machine with a **fresh `LINKIT_DATA_DIR`** (an empty folder, for example `D:\usability\P1`). Never reuse a data folder. Check that `linkit` starts and the app opens at the welcome screen.
- [ ] **LibreOffice is installed** (or install it before the session). It is needed before tailoring, not before searching, so Task 1 does not depend on it. Task 4 and Task 5 look better with it installed.
- [ ] **The AI is connected beforehand at the account level, and the participant connects it on screen.** Install and sign in to the AI tool you use (for example Codex CLI or Claude CLI, or have an API key ready to paste) before the session. Then the participant still goes through the "Connect your AI" screen as part of Task 1, because that screen is part of what we are testing. Do not make the participant create an AI account: that is outside the app and takes too long. Write down in the notes which AI you used.
- [ ] **Practice mode only.** Check the header badge says "Practice mode". Nothing is ever submitted in this study.
- [ ] **A CV ready.** Ask the participant to bring their own CV (Word, PDF, ODT or LaTeX), or copy the sample CV from `sample-cv.md` into Word and save it as `.docx` on the desktop. Put the file on the desktop so they do not have to hunt for it.
- [ ] **Prepared data for Tasks 2 and 3.** After Task 1 the participant's own search will give real results, but you cannot count on a filtered job with a clear reason, or on four applications that share one question. Prepare a second data folder (a copy of a finished run) where:
  - at least one job the participant would expect is **filtered out** with a visible reason (for example the title has "intern"), and
  - **four applications are parked** (in "Needs you", Finish applications) with the **same question**, for example "What is your notice period?".

  Use the same prepared folder for every participant so results can be compared. Switch to it before Task 2 (see `script.md`). If you cannot prepare it, stop and tell the maintainer: Tasks 2 and 3 cannot be run honestly without it.
- [ ] **For Task 4:** the first practice run with at least one filled form must exist, so the "Ready to apply for real?" task shows on Home. The prepared folder should include it.
- [ ] **Recording is optional.** If the participant agrees, start the screen and voice recording (Windows: Win+Alt+R, or the Xbox Game Bar) and save it into a local folder, never to a cloud drive.
- [ ] Print or open: the consent note, the task cards from `script.md`, `notes-template.md`, `sus.md`.
- [ ] A **stopwatch** (phone is fine). Close chat apps and mute notifications on the study machine.
- [ ] A **second person** to take notes is ideal. If you are alone, record and take only short notes during the session.

## Prepare the data folder

Tasks 2 to 4 need the prepared folder described in the checklist below. Create it with one command (about 70 fictional jobs, six filtered jobs with reasons, four parked applications that share one question, and a finished practice run):

```
uv run python scripts/seed_usability.py --data-dir D:\usability\prepared --reset
```

Add `--lang ar` for the Arabic sample CV. Start the app on it with `$env:LINKIT_DATA_DIR='D:\usability\prepared'; uv run linkit`. The script refuses your real data folder. The AI provider is preset to Codex CLI, but sign in to it yourself before the session. For Task 2, ask for "Software Engineering Intern".

## Session timing (45 minutes)

| Minutes | Part |
|---|---|
| 0–5 | Warm-up: welcome, consent, think-aloud practice |
| 5–35 | Tasks 1 to 4 (30 minutes in total, including short resets) |
| 35–45 | Debrief and SUS |

Task 5 is a separate **15-minute follow-up 7 days later**, in person or by screen share.

Suggested time limits: Task 1 is 8 minutes, Task 2 is 4, Task 3 is 5, Task 4 is 5. That is 22 minutes. The other 8 are for reading the task, resetting and switching data folders. If a task runs over its limit, stop it kindly, mark it "no", and move on.

## How to run the session

1. Read the intro in `script.md` word for word.
2. Give the participant the consent note. Wait while they read it. Ask if they agree to recording.
3. Start the stopwatch for each task when they **start working**, not when you finish reading.
4. Read each task prompt exactly. Do not explain the app. Do not point at the screen.
5. When they are stuck, use the neutral probes in `script.md`, in order. Write down every time you help.
6. Stop the task when they say they are done, when they succeed, or when the time limit is up.
7. After Task 4, hand over the SUS. Then run the debrief.
8. Thank them. Tell them when the follow-up will be, but **do not tell them what it will be about** beyond "a short task like today's".
9. After the session, delete the data folder and the copy of their CV (see "After each session").

You are an observer. If the person is silent, wait. If they ask "should I click this?", say "What would you do if I were not here?".

## How to score

**Task success, per task** (the plan target is 80% or more across Tasks 1 to 4, **without help**):

| Mark | Meaning |
|---|---|
| Yes | Done correctly, in the time limit, with no help (help level 0) |
| Partial | Done, but needed a nudge (help level 1 or 2), or the result is only half right |
| No | Not done, wrong result, over time, or you had to do it for them (help level 3) |

Only "Yes" counts toward the 80%.

**Help levels:** 0 none · 1 neutral probe ("What are you looking for?") · 2 direct hint ("Look at the top menu") · 3 you did it.

**Time:** seconds from "start working" to "done". For Task 1, stop the clock when the first search starts.

**Decisions (Task 1 only):** count each choice the participant had to make before the search started (a click that picks, types or confirms something that changes the setup). Target: 5 or fewer.

**Errors:** wrong clicks that lead somewhere unintended, confusion about wording, any moment of "I am not sure".

**Severity of each issue:**

| Level | Meaning |
|---|---|
| 1 Cosmetic | Noticed, no effect |
| 2 Minor | Slowed them down or caused hesitation |
| 3 Major | They needed help or took a wrong path |
| 4 Blocker | They could not finish, or the app could have done something they did not intend |

**SUS:** see `sus.md`. Target: 75 or more as an average.

## Safety rules for the moderator

- **Never submit a real application.** Practice mode stays on all session. Task 4 stops at the confirm dialog: the participant reads it and cancels.
- Do not enter the participant's real passwords, bank details or ID numbers anywhere. If the app asks for the vault passphrase, ask them to type a simple made-up one for the study.
- Do not use the participant's real Gmail or other email in the app. If a screen asks for it, let them say what they would do and skip it.
- The participant's CV text goes to the AI provider you connected. If they are not comfortable, offer the sample CV.

## After each session

- [ ] Save recordings (if any) in a local folder named `P<number>`; never upload them.
- [ ] Fill in `notes-template.md` within an hour, while you remember. Copy it to `docs/usability/results/P<number>-notes.md` and use the code `P1` to `P5` only. No names, no emails.
- [ ] Delete the participant's CV copy and the whole `LINKIT_DATA_DIR` for that session.
- [ ] Delete the recording once the notes are complete (see the consent note), or at the latest 30 days after the session.

## Where results go

- Per-participant notes: `docs/usability/results/P1-notes.md` to `P5-notes.md`.
- The synthesis (metrics, affinity map, issues, decisions): `docs/usability/results/synthesis.md`, from `results-template.md`.
- The issue list then feeds the UX7 fixes. The decisions section of the synthesis says what changes in `ux-plan.md` and `CLAUDE.md`.
- The `results/` folder holds quotes from real people. Keep it anonymous, and decide with the maintainer whether to commit it.
