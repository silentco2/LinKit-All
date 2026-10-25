# LinkedIn hiring posts

Many recruiters and company owners announce jobs as ordinary LinkedIn **posts**
("We are hiring a Python developer, send your CV to jobs@example.com"). These never appear on a
job board. This source reads such posts, turns the real ones into jobs, and applies through the
email address or link written in the post.

!!! warning "This breaks LinkedIn's terms of service and can get your account restricted"
    LinkedIn forbids automated access. Reading posts with a script risks a warning, a temporary
    restriction or a ban of **your own account**. The source is **off by default** and needs an
    explicit tick on "I understand the risk". Keep the limits low, and consider using an account
    you can afford to lose.

LinKit All stays on the safe side of what it controls: it never types your password, never
solves or bypasses a security check, and never comments, messages or reacts to anything. It
only reads search results.

## Signing in

1. Open **Setup** and find **LinkedIn hiring posts**.
2. Tick **I understand the risk**, then press **Sign in to LinkedIn**. A real Chrome window opens
   with its own profile (named `linkedin`, kept apart from the profiles used for applying).
3. Sign in yourself, finish any check LinkedIn shows, and close the window.
4. Press **Check session**. It only looks at your saved session and searches nothing. You
   get one of three answers: *Signed in*, *Signed out* (sign in again) or *Security check*
   (open the sign-in window and finish the check yourself).

You sign in once. Later runs reuse the saved session.

## Settings

| Setting | Meaning |
|---|---|
| **Search LinkedIn hiring posts** | The on/off switch (adds `linkedin_posts` to the enabled sources). |
| **Keywords** | One per line, English or Arabic, for example `python developer hiring` or `مطلوب مهندس`. Each keyword is one search. Keep it to about 5. |
| **Posted within** | Last 24 hours or last week. |
| **Max posts per keyword** | How many posts are read per search (default 60, at most 200). |
| **Run headless** | On by default: no browser window during runs. Turn it off to watch the browser. A visible window looks more like a normal visit, so it is less likely to be flagged. |

If you are signed out, or LinkedIn shows a security check, LinKit All **stops this source for
the run** and tells you (a notification and an event in the run log). The other sources carry
on. Fix it in Setup, then run again. It never tries to get around the check.

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

## Capturing a page for the developers

LinkedIn changes its markup often, and the post reader is written from a saved copy of a real
page. To help, save one from the command line (sign in through Setup first):

```
linkit linkedin capture --keywords "hiring python developer"
```

It opens the search headless (add `--headed` to see it), saves the page as an HTML file under the
data folder's `captures` directory (or the path given by `--out`), and prints where.

!!! warning "The file is a copy of your own LinkedIn page"
    It can contain your name, your connections and other account data. Open it and review it
    before you send it to anyone, and remove what you do not want to share.
