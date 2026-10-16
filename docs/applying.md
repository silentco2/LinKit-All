# Applying

Applying is the last stage. LinKit All opens each job's application form in a real Google Chrome
window, tailors your CV, answers the questions and, only if you allow it, submits.

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
| `min_pause_s`, `max_pause_s` | 20, 60 | Random wait between live applications |
| `headless` | off | Hide the browser window |

- Jobs are taken best score first. Sites that reached their daily cap are skipped until tomorrow.
- A dry run uses a short pause of 2 to 5 seconds.
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
3. **The Action Center**, when neither can finish.

Workday, iCIMS, Taleo and SuccessFactors have no dedicated handler yet. Jobs there go to the
generic agent, and usually stop at a sign-in page.

### How questions are answered

For every field, in this order:

1. Standard profile fields (name, email, phone, links, location) and your
   [Application answers](setup.md#5-application-answers).
2. **Sensitive questions** are answered only from your saved answers. They never go to the AI.
3. The **answer bank**: answers you gave before, matched by meaning.
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

!!! note "Where this applies today"
    Greenhouse, Lever and Ashby do not ask for an account, so nothing is created there. The
    account code is ready for handlers that need it. On other sites, the generic agent stops at
    a login or sign-up page and parks the job. Open the application page and apply by hand,
    then press **I applied by hand**.

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
- **LinkedIn Easy Apply and Indeed Apply are not built.** Automating them breaks those sites'
  terms and can get your account banned. If they are added later, they will be **off by
  default**, need an explicit opt-in with a ban-risk warning, and have low daily caps.
- Jobs that LinkedIn or Indeed list are still found. When such a posting links to the
  employer's own form (for example a Greenhouse board), that form is used. Otherwise the
  job usually stops at the site's sign-in page and is parked for you.
- Use the pauses and daily caps. They are there to keep the pace human and the numbers modest.
