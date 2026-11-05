# UX7 usability round 1 (SIMULATED): synthesis

> **This round was simulated.** AI agents played five personas on the real app on 2026-11-01. No real person took part. It finds problems early and cheaply. It **complements the study with real people (`README.md`) and does not replace it.** Read the numbers with the caveats in section 6.

Raw notes: `build/ux7/P1-notes.md` to `P5-notes.md`. Structure follows `results-template.md`.

| Item | Value |
|---|---|
| Dates | 2026-11-01 (one day; Task 5 was **not** run 7 days later) |
| App version / commit | not recorded in the notes (repo HEAD was `a11af9f` when the round was run) |
| AI provider used | Codex CLI was pre-selected and failed for all five (plan usage limit until Nov 4). Claude Code CLI 2.1.305 was used instead |
| Moderator(s) | none; each agent was its own moderator and note-taker |

## 1. Participants

| Code | Persona | Group | UI | Notes |
|---|---|---|---|---|
| P1 | Mona, accountant | non-tech MENA | English | own `.docx` CV |
| P2 | Ahmed, sales rep | non-tech MENA | **Arabic** | Arabic CV. He played the Arabic-UI role the kit gives to P3 |
| P3 | Youssef, 24, graduate, Riyadh | non-tech MENA | English | **PDF CV**, browser at **375 px** for the whole session |
| P4 | Layla, backend developer, Cairo | developer | English | checked Advanced, shortcuts, deep links |
| P5 | Omar, data engineer, Dubai | developer | English | privacy-minded, sceptical of auto-apply |

## 2. Metrics (targets from `ux-plan.md` section 14)

| Metric | Today (estimate) | V1 target | Observed | Met? |
|---|---|---|---|---|
| CV chosen to first search started | 15-30 min | 3 min or less | median **4:15** (range 3:15-8:30): P1 5:00, P2 3:30, P3 8:30, P4 3:15, P5 4:15 | **No.** The Codex failure added 1-1.5 min for everyone (P2: about 2:00 without it) |
| Decisions before the first search | 25 or more | 5 or fewer | median **6** (P1 7, P2 5, P3 8, P4 6, P5 5) | **No** (2 of 5 within target) |
| Task success, tasks 1-4, no help | n/a | 80% or more | **19 of 20 = 95%** (only miss: P3 Task 1, partial) | Yes, but see caveat on help level |
| Task 5 success | n/a | 4 of 5 | **0 of 5** (all partial; run same day, not after 7 days) | **No** |
| SUS, average | n/a | 75 or more | **60.0** | **No** |
| Derived CV fields correct | n/a | 90% or more | **39 of 45 = 86.7%** (6/7, 8/9, 5/8, 11/12, 9/9). P5's was not checked against the file | Not met on this sample; fixture set measured separately |

### Per-task results

| Task | P1 | P2 | P3 | P4 | P5 | Yes count | Median time (limit) |
|---|---|---|---|---|---|---|---|
| 1. Install to first search | Y 5:30 | Y 3:30 | **P** 8:30 | Y 4:00 | Y 4:15 | 4 of 5 | 4:15 (8:00) |
| 2. Why was a job filtered? | Y 2:30 | Y 1:00 | Y 3:15 | Y 1:30 | Y 2:30 | 5 of 5 | 2:30 (4:00) |
| 3. One answer for four applications | Y 1:30 | Y 1:30 | Y 2:00 | Y 1:30 | Y 1:45 | 5 of 5 | 1:30 (5:00) |
| 4. Turn on real applications | Y 3:00 | Y 1:00 | Y 4:30 | Y 2:30 | Y 2:30 | 5 of 5 | 2:30 (5:00) |
| 5. Return after 7 days | P 5:00 | P 5:30 | P 6:30 | P 6:00 | P 8:00 | 0 of 5 | 6:00 (5:00) |

Help level was 0 everywhere. Task 4: nobody pressed Confirm and the badge stayed on Practice mode every time, but P1, P3, P4 and P5 could not say whether each application would still ask first. Task 5: nobody reached a filled form. P2, P4 and P5 hit "LibreOffice not found" in the apply run. P1 and P3 stopped the run after it stayed silent for 25 s.

### SUS (scores re-added from the raw answers; all match the notes)

| P1 | P2 | P3 | P4 | P5 | Average |
|---|---|---|---|---|---|
| 60 | 55 | 50 | 72.5 | 62.5 | **60.0** |

### Differences between groups

- **Non-tech (P1-P3), SUS mean 55.0. Developers (P4-P5), mean 67.5.** Non-tech people stalled on the red LibreOffice / `linkit doctor` box and the raw AI error. Developers read the same boxes fine but wanted proof: the CV diff, what leaves the computer, real values behind the ticks.
- **Arabic UI (P2):** setup read well in Arabic. Anything produced while running (errors, parked questions, reasons, logs) fell back to English, with bidi and mixed-digit problems.
- **Phone width (P3):** no horizontal scroll on any wizard step, but the safe-state signals moved into Menu.

## 3. Affinity themes

"Participants" is how many of the five hit it. Theme Tn maps to issue Un in section 4.

| Theme | Participants | Worst severity | Tasks |
|---|---|---|---|
| T1 No path to start applying after approving a job. Home keeps saying "Finish 1 application" or "Review 7 possible matches". Apply is hidden in Activity > Advanced, behind a button called "Find new jobs" (run titled "Search 2"). The run then takes all 10-18 ready jobs, not the one approved | 5 of 5 | 3 | 5 |
| T2 AI usage-limit error shown raw, printed twice, with "Upgrade to Pro" and a URL. "Try again" repeats it. In an apply run it ends as "failed", although the text promises a pause. No "pick another AI" hint. English only for P2 | 5 of 5 | 3 | 1, 5 |
| T3 LibreOffice blocks practice. A red box at CV upload and a Home task offer only `linkit doctor` in a terminal. The practice Apply run fails with "LibreOffice not found". P3's PDF step says "open the preview" when none exists | 5 of 5 | 3 | 1, 4, 5 |
| T4 Go-live checklist shows four static green ticks ("CV is approved", "limits are set") with no values and no links, and contradicts the LibreOffice task above it | 4 of 5 (P1, P3, P4, P5) | 3 | 4 |
| T5 Privacy over-claim. "Everything stays on this computer" sits next to a step that sends the CV to an AI provider. Searches also go to job sites. No single statement of what leaves. English-only AI text is never stated | 4 of 5 unclear (P1, P2, P3, P5); P5 called it a contradiction | 3 | 1 |
| T6 Filter reason is shown but cannot be acted on. No "Show me why" and no link to the setting. P2 is a sales rep and "sales" is excluded. The funnel has no "filtered" count | 5 of 5 | 3 | 2 |
| T7 Arabic: English leftovers in errors, parked questions, AI reasons, logs. Bidi faults: "٧/10" shows as "10/٧", a sentence starting "LinKit" is laid out LTR, "?" lands on the wrong side. Bad counts ("10 جزءًا"). Mixed digit styles. City "الإسكندرية, Egypt" | 1 of 1 Arabic-UI user | 3 | all |
| T8 Phone width (375 px): Practice mode badge and Needs-you count hidden in Menu. Go-live panel opens below the fold. Toast covers the next card's buttons. Tap targets 24-30 px. Reason chips cut off | 1 of 1 phone user | 3 | 1, 3, 4 |
| T9 CV inference wrong or empty. Level preselected lead/manager/executive and senior off for 10-11 years (P1, P5) and "expert / team lead" for a sales rep (P2). An internship-only CV gave no title, company, years or level (P3). "github" extracted as a skill (P4) | 5 of 5 | 3 | 1 |
| T10 Stale or conflicting counts. Needs-you badge (13, 9) differs from Home's "5 applications"; tab and badge counts do not drop after Approve until reload; funnel flashes 0; "18 jobs ready" after approving 8 | 5 of 5 | 2 | 1, 3, 5 |
| T11 Indeed country bug. Sources says "Indeed searches in U.S. Virgin Islands, from your places" when the place is Egypt. Could be a seed artefact; not reproduced | 1 of 5 (P5) | 3 | 2 |
| T12 Salary input. The grey "30000" looks like a filled value. Currency is a 166-item native list that starts at AED even for an Egypt user. Number spinner, no thousands separator | 4 of 5 (P1, P3, P4, P5) | 2 | 1 |
| T13 "Use this for every application" is unclear (these four, or all future ones?). P5's answer was saved as a standing answer with the box unticked | 4 of 5 (P1, P3, P4, P5) | 2 | 3 |
| T14 Real-apply confirm ("from now on") does not say each application still asks first. The risky button is the blue primary. "Submit without asking" is hidden in Settings > Advanced | 4 of 5 (P1, P3, P4, P5) | 3 | 4 |
| T15 Go-live entry is a small link under the LibreOffice task. Thumbnails are tiny or open a raw image that drops out of the app (Back closes the panel). No CV red-line diff | 5 of 5 | 2 | 4 |
| T16 Internal words: State filter (discovered, enriched, ranked, scored), "Practised", "Find new jobs" on an apply run, `claude_cli (default model) ok` | 5 of 5 | 2 | 1, 2, 5 |
| T17 Silent or raw activity: apply run silent 25-80 s, raw "RuntimeError: Google returned no job data" in orange, Stop gives no "stopped" notice | 4 of 5 (P1, P2, P4, P5) | 2 | 1, 5 |
| T18 Needs-you cards carry 5-8 controls and no clear main button; the last select has no save button; blue "This job only" is a toggle | 3 of 5 (P2, P3, P4) | 2 | 3 |

**Voices** (at most two per theme):

- T1 P5: "I approved it. Now where is the button that applies? 'Find new jobs' isn't it." P3: "I approved one job, so why can't I just apply to it?"
- T2 P3: "Upgrade to Pro? Did I do something wrong? Do I have to pay?" P4: "It says the search pauses and continues later. It didn't. It failed, twice."
- T3 P1: "What is LibreOffice? What is 'linkit doctor'? I don't have a terminal." P3: "I don't know what 'linkit doctor' is, is it a virus?"
- T4 P5: "I never approved a CV and never set a limit. Who ticked these?" P4: "All four ticks are green but two lines above it says LibreOffice isn't installed. Which one is lying?"
- T5 P5: "'Everything stays on this computer', yet I'm connecting an AI that reads my CV. Which is it?"
- T6 P1: "I never typed 'intern' anywhere, who decided that?" P3: "OK, it says why. But where do I change it?"
- T7 P2: "حلو وبالعربي، بس لما حصل خطأ كله بقى إنجليزي." (Nice, and in Arabic, but when an error happens it all turns English.) P2: "لما يقولي يتوقف أو يفشل، يقولي بالعربي أعمل إيه." (When it stops or fails, tell me in Arabic what to do.)
- T9 P1: "Why does it think I'm a manager?" P4: "'github' is not a skill."
- T10 P3: "Apply to 18 jobs? I only approved 8."
- T12 P1: "I'm paid in EGP. Why AED?" P5: "Where did 30000 come from? Did you guess it?"
- T13 P1: "'Every application'? Every one of what? I'll leave that." P4: "'Every application' - every one of these four, or every future one? Say which."
- T14 P1: "'From now on'... does that mean it sends everything without asking me?" P3: "So it sends my CV in my name and I can't take it back. I'm not pressing that."
- T16 P4: "Practised = applied in practice mode? Then say 'practice-applied'."
- T17 P1: "Did something break? It's orange."
- T8, T11, T15, T18: no direct quote; observations only.

## 4. Issues list

Severity: 1 cosmetic, 2 minor, 3 major, 4 blocker. Impact = worst severity x participants. Effort: S under half a day, M 1-2 days, L more. **Status shows the fix commit: 92709c3 (frontend), ba46591 (backend), 717f827 (frontend).** Status as of HEAD 717f827.

| ID | Issue (theme) | Sev | Part. | Impact | Effort | Suggested fix | Status |
|---|---|---|---|---|---|---|---|
| U1 | No path to apply after approving (T1) | 3 | 5 | 15 | M | Home's main button points at "Apply to N jobs (practice)" as soon as any job is approved or queued, ahead of review work. Label the Activity button "Apply". Say how many jobs a run will take | Fixed (717f827, ba46591) |
| U2 | Usage-limit error raw, doubled, run "failed" (T2) | 3 | 5 | 15 | M | One plain sentence ("Your ChatGPT plan is out of messages until Nov 4"), shown once, with a "Use another AI" button. Park the run as paused, not failed. Translate | Fixed (ba46591, 717f827) |
| U3 | LibreOffice blocks practice, fix is a terminal command (T3) | 3 | 5 | 15 | M | Explain in plain words, not a red alert. Offer an in-app install action, not `linkit doctor`. Do not hard-fail practice apply, or say clearly why. Drop the "open the preview" text when there is no preview | Fixed (ba46591, 717f827) |
| U4 | Go-live checklist ticks are static (T4) | 3 | 4 | 12 | S | Compute each tick from real state (CV approved, limits changed, LibreOffice present). Show the value and link to its setting. An untrue tick shows as a to-do | Fixed (ba46591, 717f827) |
| U5 | Privacy over-claim (T5) | 3 | 4 | 12 | S-M | Replace the claim with the exact one: files stay here, CV text goes only to the AI you pick, searches go to the sources you list. Add a "What leaves this computer" panel linked from welcome and from the go-live card. State English-only AI text. `script.md` repeats the claim in its intro: fix it too | Fixed (717f827; `script.md` intro fixed) |
| U6 | Filter reason with no way to change it (T6) | 3 | 5 | 15 | S | A button on the reason ("Allow 'sales'") or a link to Settings > Jobs & places > Filters. Add a "filtered" step to the funnel | Fixed (92709c3) |
| U7 | Arabic leftovers and bidi (T7) | 3 | 1* | 3 | M | Translate generated strings (errors, reasons, log and history lines). Show the original parked question with an Arabic gloss beside it. Use `dir=ltr` or `bdi` for scores and numbers. Fix plurals and the digit style | Fixed (92709c3, ba46591) |
| U8 | Phone width: badge and count hidden (T8) | 3 | 1* | 3 | M | Keep the Practice mode badge and Needs-you count in the top bar. Scroll expanded panels into view. Raise tap targets to 40 px. Move the toast clear of buttons | Fixed (92709c3) |
| U9 | CV inference wrong or empty (T9) | 3 | 5 | 15 | M | Do not infer manager/executive from years alone. Count internships. Take skills only from a skills section. Keep the rule that nothing is written until the user confirms | Fixed (ba46591) |
| U10 | Stale and conflicting counts (T10) | 2 | 5 | 10 | S-M | One source for Home and Needs-you counts. Update tabs and badge on Approve. Do not show 0 before the load finishes | Fixed (92709c3) |
| U11 | Indeed country mapping (T11) | 3 | 1 | 3 | S | Reproduce with a fresh Egypt place. If it is real, fix the place-to-country map | Fixed (ba46591); not re-checked on a real Egypt place |
| U12 | Salary input (T12) | 2 | 4 | 8 | S | Example text, not a number, as placeholder. Default the currency from the home country. Searchable list. Text input with thousands separators | Fixed (92709c3) |
| U13 | "Use this for every application" wording (T13) | 2 | 4 | 8 | S | Say what it does ("Also use this answer for similar questions later"). Check that an unticked box does not save a standing answer (P5 saw one) | Fixed (92709c3) |
| U14 | Real-apply confirm does not say each one still asks (T14) | 3 | 4 | 12 | S | State the actual setting in the confirm ("LinKit will still ask before each one"). Make Cancel the safe default. Link to "Submit without asking" | Fixed (717f827) |
| U15 | Go-live entry, thumbnails, no CV diff (T15) | 2 | 5 | 10 | S-M | Put "Ready to apply for real?" in the main Home card when practice has run. Open thumbnails in an in-app viewer. Add the CV red-line diff | Fixed (d821983; lightbox and tailored-CV link in 717f827) |
| U16 | Internal words (T16) | 2 | 5 | 10 | S | Hide internal states in the filter. Rename "Practised". Name the apply button "Apply". Do not print `claude_cli (default model) ok` | Fixed (d821983, 60b9c97) |
| U17 | Silent runs, raw log text, no "stopped" notice (T17) | 2 | 4 | 8 | S-M | Per-job lines during apply, a plain-words version of known errors, a "Stopped" state | Fixed (d821983, 93637ec; log lines translated in 717f827) |
| U18 | Needs-you card has too many controls (T18) | 2 | 3 | 6 | S | One main button. Move the rest into a menu. A select answer needs a Save button | Fixed (52b068e) |

\* One person tested this condition (Arabic UI, 375 px). Impact is low only because of the sample. For Arabic readers and phone users it applies to everyone.

**Do first** (impact 12 or more, effort S): U4, U6, U14. **Then** the M items with impact 15: U1, U2, U3, U9. U5 is mostly copy and quick.

Smaller items, one line each (all fixed: d821983, 60b9c97, 52b068e; the select-all focus and shareable URL items were already done in 92709c3):

- Practice badge missing on the welcome screens (P3, P5).
- Level chips: "all lit" is not explained (P1, P3).
- Riyadh asks "Can you work here?" again after Saudi Arabia (P3).
- Select-all leaves focus on the checkbox, so J and X stop working; Ctrl+Z is not mapped (P4).
- Backspace on an empty tag box deletes a chip with no warning (P4).
- Added source lands at the bottom as a raw URL and the "1 of 117 on" counter does not change (P4).
- Job history runs words together, with US dates; the drawer has no shareable URL (P3, P4, P5).
- Phone flag shows as the letters "EG" on Windows (P1, P2).
- Filename shows `.docx` after a PDF upload; "5 text parts found" is unclear (P3).
- The Home "Next" card ignores the 8-job approve queue behind a parked application (P2, P3, P4, P5).

## 5. What worked

- **One answer for several applications.** Fastest task for everyone (median 1:30, 5 of 5). P1: "It put the four together. Good, one answer, I like that." P4: "Four applications, one question, one box. That's what I wanted." P2: "كده الأربعة خلصوا مرة واحدة، حلو." (All four done at once, nice.)
- **Practice mode.** Understood and trusted in all five sessions. P1: "The Practice mode label made me relax." The "Find jobs (practice mode - nothing is submitted)" button was liked by P1, P2 and P3.
- **Sensitive questions stay local.** P5: "'Sensitive: this was never sent to the AI.' That is exactly what I wanted to read." P3 called it "very good". "Ask me each time" as the default reassured P1, P3 and P5.
- **Funnel numbers are links; reason chips on rows.** P4: "The funnel numbers are links, the changed-value marks and the reset link are exactly what I wanted." Everyone who opened a filtered job read the reason correctly.
- **Source badges** ("From your CV", amber "check this") were read and understood by P1, P2 and P5. "Counted from your CV dates" helped P1 and P4.
- **Confirm text for real applications** was blunt and understood. Nobody pressed Confirm. P5: "The confirm wording is blunt, which I like: 'cannot be taken back'."
- **Advanced settings.** P4: "Advanced is better than I expected." (pickiness numbers, "(1 changed)", reset). Deep links such as `/jobs?state=filtered_out&q=Backend` reload straight into the right view.
- **City picker and phone split** worked for P1, P2 and P3. No horizontal scroll at 375 px on the wizard.

## 6. Caveats of the simulation

- **Not real people.** Agents cannot feel real worry, shame or boredom. The SUS answers are simulated. The mean (60.0) shows direction, not a score to compare with the 68 average. The AI-error and "Do I have to pay?" reactions are plausible but unproven.
- **Help level was always 0.** Nobody was there to probe or hint, so task success is probably too high. No participant asked for help.
- **Native file picker bypassed.** The CV was attached by script (`DataTransfer` on `input[type=file]`). "Find the upload" and "which file?" were not tested.
- **Prepared data belonged to another persona** (Layla Hassan, backend developer). Tasks 2-5 showed developer jobs with 90% "strong" for an accountant, and P5 kept saying "this isn't me". No task card existed for Task 2: P1 saw the filtered list once before starting, so her first step is not clean.
- **Codex was out of quota** on this machine. Every participant went through the usage-limit path, so T2 is 5 of 5 here. A real user may never see it. It also added 1-1.5 min to Task 1.
- **LibreOffice was not installed.** The kit says to install it first. Without it, the red box showed in every first run and Task 5 could not finish. A real user on a fresh `uv tool install` is likely to see the same box, so T3 is real, but the 5 of 5 is partly this machine.
- **Timing is estimated** (10-20 s per step plus waits), not measured. Five agents shared one machine and browser pane: focus was stolen, screenshots glitched, and ports were shared (P2 stopped an `http.server` on 8830 that may have been P3's).
- **Task 5 was not after 7 days.** It ran straight after Tasks 2-4 on the same folder, so a parked application from Task 3 changed what Home showed. This measured "can you get from Home to applying", not memory.
- **P5's derived-field check** was not compared with the CV file. The fixture accuracy is measured separately.
- **The script was out of step with the app** ("Show me why", "Use this for similar questions"). Fixed: `script.md` now uses "Why was this left out?" and the Needs-you wording.

## 7. Next step

1. U1-U18 and the smaller items are fixed (92709c3, ba46591, 717f827, d821983, 93637ec, 60b9c97, 52b068e).
2. **Rerun with five real people** using the kit (`README.md`, `script.md`). Before that:
   - install LibreOffice (or run `linkit install-libreoffice`);
   - sign in to an AI that has quota;
   - seed a prepared folder that matches each participant (the seed script gives Layla's data to everyone);
   - (done) `script.md` uses the app's words;
   - run Task 5 seven days later on a restored folder.
3. Retest first: U1 (apply from Home), U2 (limit error), U3 (LibreOffice), U4/U14 (go-live), U6 (filter reason), U9 (CV inference).
4. Keep this file as the baseline. Targets not met here: first search 3 min, decisions 5, Task 5, SUS 75.
