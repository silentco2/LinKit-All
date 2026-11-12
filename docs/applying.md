---
title: "Auto-fill job applications: Greenhouse, Lever, Ashby"
description: "How LinKit All fills job applications in your own browser: Greenhouse, Lever and Ashby handlers, an AI form agent, accounts, email codes, Practice mode."
---

# Applying

Applying is the last stage. LinKit All opens each job's application form in your installed browser
(Chrome, Edge or Brave), tailors your CV, answers the questions and, only if you allow it, submits.

!!! warning "Live applying sends real applications in your name"
    Submitted applications cannot be taken back. Start with a dry run, look at the screenshots,
    and only then turn on live mode. The first live run should be one you watch.

## Dry run and live

| Mode | What happens | How to get it |
|---|---|---|
| **Dry run** (default) | Fills the form, takes screenshots, **never clicks Submit**. | Do nothing |
| **Live, confirm each** | Fills the form, then waits for your click on **Submit application** in the Action Center. | Turn on *Submit real applications* |
| **Live, no questions asked** | Submits as soon as the form is filled. | Also turn on *Submit without asking me first* |

The left menu always shows **Dry run** or **Live applying**. In dry-run mode the Submit
click is blocked twice in the code: the run returns before the submit step, and the click
function itself refuses. A dry run records what it filled (visible in the job's panel, with
screenshots) and marks the job so that the same job is not dry-run again and again.

Each job also gets a screenshot before submit and one after.

### Confirm before submit

In live mode with *Submit without asking me first* off, each filled form is parked in the
Action Center as **Ready to submit**. You see the screenshot and a table of everything that
was filled, with where each answer came from (profile, saved answer, AI, file). Press
**Submit application**, or **Skip**. Your click requeues the job, and the next Apply run
submits it.

### Applied only on proof

A job becomes `applied` only when the site's confirmation page is seen. Handlers look for
that site's own confirmation text. The generic agent looks for phrases such as "thank you
for applying". If the page still shows form controls, it asks the AI to make sure the page
is not just a form again.

If there is no confirmation, the job is never assumed applied. It is parked in the Action
Center (a CAPTCHA or form errors) or marked `failed` with the reason. A Playwright trace is
kept for failed jobs. If you submitted something yourself, press **I applied by hand**.

## Limits and pauses

| Setting | Default | Meaning |
|---|---|---|
| `max_per_run` | 10 | Jobs handled in one Apply run |
| `daily_cap_per_site` | 20 | Live submissions per site per day |
| `min_pause_s`, `max_pause_s` | 20, 60 | Random wait between two live applications on the same site |
| `parallel_sites` | 3 | Sites worked on at the same time (1 to 3) |
| `headless` | off | Hide the browser window |

- Jobs are taken best score first. Sites that reached their daily cap are skipped until tomorrow.
- Different sites are worked on at the same time, up to `parallel_sites`. A "site" is the
  ATS (all Greenhouse boards are one site, all Lever boards another) or, for the generic
  agent, the host of the apply link. On one site, jobs go one at a time, best score first,
  with the random pause between them. The pause never waits for another site. Set
  `parallel_sites = 1` to work through sites one after the other.
- A dry run uses a short pause of 2 to 5 seconds.
- The Live Run picture shows the latest frame from whichever site is working.
- Each site gets its own Chrome profile, so sessions last between runs. The window is visible
  by default so you can step in.
- If your AI plan hits a limit, or LibreOffice is missing, the Apply stage stops with a clear
  message. The rest of the jobs keep their state and wait for the next run.

## Handlers and the generic agent

LinKit All picks the method for each job.

1. **A dedicated handler** for the job's ATS. Built today: **Greenhouse, Lever, Ashby**.
   Each knows how that form is laid out. No account is needed on these.
2. **The generic AI form agent** for any other site (turn it off with `generic_agent = false`).
   For each page it takes a snapshot of the visible form controls and asks your AI to map them
   to fields (one AI call per page). Then **our code** fills the fields, checks for errors,
   and presses Next. The model only decides; it never drives the browser. It follows at most
   8 pages, and then gives up.
3. **The Action Center**, when neither can finish. The job then waits in **Needs you** as
   "Finish this one yourself", with the link, your CV and the answers prepared so far.

Jobs found on job boards (Built In, Bayt, Torre, RemoteOK, ...) usually link to a job ad, not
a form. The agent presses the ad's **Apply** button, closes a cookie or sign-in popup in the
way, and follows where it leads (up to 3 steps). When that is a Greenhouse, Lever or Ashby
form, the dedicated handler takes over.

Workday, iCIMS, Taleo and SuccessFactors have no dedicated handler yet. Jobs there go to the
generic agent, which signs in or signs up as described below.

### Test every kind of application

```bash
linkit apply-probe
```

This runs one job per source in Practice mode (nothing is submitted, and your CV is sent as
uploaded) and writes a report to `applications/probe_<date>.md` in the data folder. The report
shows, per source, whether the form was filled and ready to submit or why it stopped. Use
`--job ID` (repeatable) to try exact jobs.

### How questions are answered

For every field, in this order:

1. Standard profile fields (name, email, phone, links, location) and your
   [Application answers](setup.md#5-application-answers).
2. **Sensitive questions** are answered only from your saved answers. They never go to the AI.
3. The **answer bank**: answers you gave before, matched by meaning. Each answer is **General**,
   **Per role** or **Per company**, decided from the question's wording. "Why do you want to work
   here?" is kept per company and "Why are you a good fit for this role?" per role, so an answer
   written for one company is never sent to another.
4. An **AI draft** written from your CV and non-sensitive profile facts. These are saved to the
   answer bank marked as AI, so you can edit them on the **Answer bank** page.
5. If a required question is still open, the job is parked for you.

A **cover letter** is written only when the form has a cover-letter field.

Optional acknowledgements (for example marketing emails) are never ticked. Required privacy
and legal ones are ticked only if you chose "Accept for me" in the wizard.

## Accounts and verification email

Some sites need an account before you can apply. The account machinery is built:

- A strong random password is generated for the site, following its rules.
- It is saved to the encrypted [vault](privacy.md#the-vault) **before** the sign-up form is
  submitted, so a crash never loses it. One vault entry is kept per site and employer.
- If the site sends a verification code or link, LinKit All reads it from your mailbox (see the
  [Email step](setup.md#8-email)) and finishes the sign-up. Plain pattern matching comes first. Only
  if that finds nothing is the email text (up to about 4,000 characters) sent to your AI.
- Next time, the saved login is used.

In a **dry run**, sign-up forms are never touched. The outcome just says an account would be
created. In **live** mode the account is created automatically when needed, and the
application itself still waits for your click unless you turned that off.

If the vault is locked, the mailbox is not connected, or the site asks for a sign-in code
(2FA), the job is parked in the Action Center.

!!! note "Where this applies"
    Greenhouse, Lever and Ashby do not ask for an account, so nothing is created there. On job
    boards and other sites, the generic agent first tries [Sign in with Google](#sign-in-with-google)
    if you turned it on. Then it uses the saved login for that site, or (live only) creates one
    with a vault password and confirms it from your mailbox. Sites that need a phone check or a
    CAPTCHA still park the job for you.

### Sign in with Google

Many job sites offer "Sign in with Google". LinKit All can use it to sign up or sign in on those
sites, with no password and no verification email.

1. Open **Settings > Accounts & email** and press **Sign in to Google**. This also turns on
   **Use my Google account on job sites**.
2. Sign in yourself in the Chrome window that opens, then close it. This is done once.

In **live** mode, when the form agent reaches a login or sign-up page with a Google button, it
presses the button, picks your account (the one matching your profile email, else the first) and
presses **Continue** on Google's consent screen. That consent gives the site your name and email.
Then it goes back to the application form. The application itself still waits for your click
unless you turned that off.

LinKit All never types your Google password and never solves Google's checks. If Google asks for
a password, a two-step code or a challenge, the job is parked in the Action Center. A **dry run**
never presses the button. A site without the button is parked as before.

## CAPTCHAs

LinKit All **never solves a CAPTCHA**, and never pays for a solving service. When one
appears, the job is parked in the Action Center with a screenshot, and its page is closed.
You have two choices:

- Press **Open application page**, finish the application yourself in your own browser, then
  press **I applied by hand**.
- Press **Retry** to let LinKit All try again from a fresh page. Each site keeps its own
  Chrome profile, which sometimes means the CAPTCHA does not appear the second time.

Lever uses hCaptcha, and Greenhouse and Ashby can use reCAPTCHA, so expect this on live runs.

## Terms of service notes

- **Company forms** (Greenhouse, Lever, Ashby and similar) are what their owners publish for
  applicants. Automation can still be against a site's terms, so you apply at your own risk.
- **LinkedIn, Indeed and Glassdoor are never automated** (`apply.assisted_hosts`). Their terms
  ban it and accounts get banned. These jobs wait in **Needs you** as "Apply in your own
  browser". Press **Open in my browser**: the job opens in your normal browser, where you are
  signed in. The **LinkIt Fill** extension then fills each step with the answers LinKit All
  prepared, and marks anything only you can answer in orange. You press Next and Submit.
  What you type into a field it left empty, or change in one it answered from a saved answer or
  the AI, is saved in **Settings > Answers** for next time. Sensitive questions, passwords,
  codes, ID numbers, tick boxes, dates and cover letters are not saved.
  When the site confirms, the job is marked applied. Set it up once in
  **Settings > Applying > Apply in your own browser**: load the extension folder shown there
  with "Load unpacked" on `chrome://extensions`, then paste the pairing code into its options.
  That code is all it needs: LinKit All tells it the port each time it starts. The extension
  only talks to LinKit All on this computer. It also fills forms inside embedded frames.
- LinkIt Fill works out which waiting job a page is from the site's job id, then the address,
  then the job's title and company on the page. It never guesses: a page that is none of your
  waiting jobs shows no panel. On any page you can **right-click and choose Fill with LinkIt**:
  it reads every label and empty field on the form (dialogs and embedded forms too) and fills
  them from your saved data. What is not recorded goes to the AI, optional fields included, and
  the answer is saved. On a page that is none of your waiting jobs, answers tied to a role or a
  company are filled but not saved.
- Some LinkedIn jobs are not Easy Apply but link to the employer's own site. LinkedIn only shows
  that link to signed-in members, so the card says so: press Apply on LinkedIn in your browser,
  and the LinkIt panel follows you to the employer's form. Press **Fill this step** there.
- When a LinkedIn or Indeed posting links to the employer's own form (for example a
  Greenhouse board), that form is used and filled by the app as usual.
- Use the pauses and daily caps. They are there to keep the pace human and the numbers modest.
