# LinkedIn hiring posts

Many recruiters and company owners announce jobs as ordinary LinkedIn **posts**
("We are hiring a Python developer, send your CV to jobs@example.com"). These never appear on a
job board. This source reads such posts, turns the real ones into jobs, and applies through the
email address or link written in the post.

!!! warning "This breaks LinkedIn's terms of service; you use it at your own risk"
    LinkedIn forbids reading its pages with a script, and Google may decide your searches look
    automated and ask you to prove you are not a robot. No LinkedIn account is used, so none can
    be restricted, but Google can slow down or block searches from your network for a while. The
    source is **off by default** and needs an explicit tick on "I understand the risk". Keep the
    keywords few.

LinKit All stays on the safe side of what it controls: it never signs in anywhere, never solves
or bypasses a check, and never comments, messages or reacts to anything.

## How posts are found

1. For each keyword, Google is searched for `site:linkedin.com/posts <keyword>`, limited to the
   last day or week. This runs in a real Chrome window with its own profile (named `google`,
   kept apart from the profiles used for applying), at a reading pace.
2. Each result is opened only as far as Google's redirect, to learn the post's address. The
   date is in the post's address, so older posts are dropped before anything is fetched.
3. The public post page is read for the post text, author and date. Only the post itself is
   read, never the comments under it.

## When Google asks for a check

If Google shows its "unusual traffic" check (a reCAPTCHA) or asks you to choose cookie
settings, LinKit All **stops this source for the run**. The other sources carry on. The run log
says why, and **Settings > Sources > LinkedIn hiring posts** shows a red note.

1. Press **Solve Google check**. Chrome opens Google with the same profile the searches use.
2. Answer what Google shows yourself, then close the window.
3. Run again.

LinKit All never solves the check for you. If checks come often, use fewer keywords, run less
often, or turn off **Run headless**.

## Settings

| Setting | Meaning |
|---|---|
| **Search LinkedIn hiring posts** | The on/off switch (adds `linkedin_posts` to the enabled sources). |
| **Keywords** | One per line, English or Arabic, for example `python developer hiring` or `مطلوب مهندس`. Each keyword is one Google search of up to 5 result pages. Only the first 5 keywords are used. |
| **Posted within** | Last 24 hours or last week. Google is asked for this window, and posts older than it are dropped. |
| **Max posts per keyword** | How many posts are read per keyword (default 30; Google gives at most 50). |
| **Run headless** | On by default: no browser window during runs. Turn it off to watch the browser, or if Google asks for checks often. |

## What happens to a post

- A post that points to a known applicant tracking system (Greenhouse, Lever, Ashby and so on) is
  sent straight to that system's plugin, like any pasted company link. No AI is used.
- Other posts are read by your AI provider in batches of about ten. For each it extracts the
  role, company, location, how to apply (email, form or link), the email and the link.
- Posts from job seekers ("open to work") and posts without an email address or link
  ("DM me", "comment below") are dropped. The scam and ghost checks of the
  [trust filter](trust.md) apply to these jobs as well.

A job from a post shows "From a LinkedIn post by ..." in its panel, with a link to the post and
how to apply.

## Applying to these jobs

**By email.** If the post gives an email address, LinKit All applies by email:

- It sends from your Gmail or Yahoo account over SMTP, using the app password already in the
  vault (the one you saved for [email verification](setup.md)). The vault must be unlocked.
- The message is short. The greeting and signature are written by the program, and the AI writes
  only the body, from your CV and profile. It cannot invent anything you did not provide.
- Your tailored CV is attached as a PDF.
- **Dry run** (the default) sends nothing. It writes an `.eml` file you can open in a mail
  program, and shows the message in the job's panel.
- **Live, confirm each** parks the job in the [Action Center](action-center.md) as a
  **Confirm before emailing** card with the To, Subject, Message and attachment. Edit the
  subject or message, press **Save draft**, then **Confirm and send**, or **Skip**.
- **Live, no questions asked** sends as soon as the email is ready.
- The daily cap is **15 emails** by default. Change it under **Application emails per day** in the
  Email step of Setup. Keep it low.
- LinKit All never emails the same address twice, even for a different job.
- A sent email counts as **applied (by email)**. The sent message, saved with the job, is the
  proof. There is no confirmation page to wait for.

Press **Send a test email to myself** in the Email step to check that sending works before the
first real application.

**By form or link.** If the post gives a link instead, the job goes through the normal
[applying](applying.md) flow: a known ATS handler if there is one, otherwise the generic form
agent, with the same dry-run and confirm rules.
