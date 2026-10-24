# Setup wizard

Run `linkit`, then open **Setup** in the left menu. The wizard has nine steps. You can visit
them in any order and come back later. A tick shows a finished step.

If you prefer files to forms, two steps have a command-line twin:
[`linkit profile import`](cli.md#linkit-profile-import) and
[`linkit search import`](cli.md#linkit-search-import). Examples are in
[`profile.example.json`](profile.example.json) and [`search.example.toml`](search.example.toml).

## 1. Profile and CV

**Your profile**

| Field | Used for |
|---|---|
| Full name, email, phone, location | Application forms, and your CV's contact details |
| Skills (one per line) | Ranking, and the only extra skills tailoring may mention |
| Locked facts (one per line) | Text the AI must never change: employers, job titles, degrees |

Numbers, dates and contact details are always locked, even if you list nothing.

**Your CV.** Upload a Word (`.docx`), OpenDocument (`.odt`), PDF or single-file LaTeX
(`.tex`) file. Only words are ever changed, never layout or style. Maximum size is 10 MB.

- **Word and LaTeX** are the most reliable.
- **ODT** is converted to Word by LibreOffice.
- **PDF** is converted to Word once. Conversion can garble text or layout, so you get a
  preview. LinKit All will not tailor or apply with this CV until you press **Approve this
  as my CV**.
- **LaTeX** files must be one self-contained file (no `\input`) and need Tectonic.

After uploading, the page lists the numbered text parts it reads from your CV. Check that
they look right.

## 2. AI

Pick one provider: ChatGPT plan (Codex CLI), Claude plan (Claude Code CLI), API key, or a
local model. The wizard shows which CLIs are installed. Press **Test connection**, then
**Save**. See [Install](install.md#ai-providers) for the details of each.

For an API key, set `LINKIT_API_KEY` in your environment. The wizard does not take the key.

## 3. Search

- **Job searches**, one per line (for example `python developer`). A `/` between words makes
  separate searches: `React/Next.JS Developer` becomes `React Developer` and `Next.JS Developer`.
- **Locations**, one per line. Leave it empty for anywhere.
- **Posted within (days)** and **Max results per search, per site**.
- **Job sites**: LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter, Wuzzuf, Bayt and Forasna.
- **Country for Indeed.** Glassdoor is searched without a country.
- **Company career pages**, one per line. Paste any careers page link. See [Sources](sources.md).

## 4. Filters

Free rules that drop jobs before any AI is used: title words, locations, work mode
(remote, hybrid and on-site are all checked by default), minimum monthly salary with its
currency (only postings in that currency are compared), seniority, companies to avoid, and "at most one job per company".
This step also holds the AI scoring settings: the score for auto-apply, the score for
your review queue, how many jobs go to the AI per run, and jobs per AI call.
See [Matching](matching.md).

## 5. Application answers

Application forms ask the same things again and again. Answer them once here.

- **Basics:** first and last name (optional overrides), city, country, current company and
  title, LinkedIn, GitHub and portfolio links, years of experience, notice period, a default
  for "How did you hear about us?", and whether you would relocate.
- **Work and visa (sensitive):** countries you can legally work in, whether you need visa
  sponsorship, salary expectation and currency.
- **Voluntary demographics:** gender, race or ethnicity, Hispanic or Latino, veteran status,
  disability. Each is optional.
- **Acknowledgements:** whether LinKit All may accept required privacy notices, and whether
  it may accept required legal agreements and "I certify my answers are true" statements.

Anything you leave on **Ask me when a form needs it** is never guessed. The job waits in the
[Action Center](action-center.md) and asks you. LinKit All never picks "Prefer not to say"
for you either; you have to choose it.

!!! warning "Legal acknowledgements"
    "Accept for me" on legal agreements means LinKit All will tick arbitration agreements and
    "I certify" boxes in your name. Only choose it if you are comfortable with that.

## 6. Applying

| Setting | Meaning |
|---|---|
| Submit real applications (live mode) | Off means dry run. See [Applying](applying.md). |
| Submit without asking me first | Only in live mode. Off means each application waits for your click. |
| Max applications per run | Default 10 |
| Daily cap per job site | Live submissions per site per day. Default 20 |
| Shortest and longest pause | A random wait between live applications. Default 20 to 60 seconds |
| Hide the browser window (headless) | Off by default. You usually want to see Chrome. |
| Use the AI form agent | For sites without a dedicated handler |

The left menu shows **Dry run** or **Live applying** at all times.

## 7. Vault

The vault stores, encrypted on this computer, the passwords LinKit All makes for job sites
and your email app password. It is optional. Without it, applications that need an account
wait in the Action Center.

Choose a passphrase of at least 8 characters. **It cannot be recovered.** If you forget it,
you have to start a new vault. "Remember on this computer" keeps the key in your system
keyring so the vault opens by itself next time; turn it off on a shared computer.

## 8. Email

Some job sites email a code or link to confirm a new account. If you connect your mailbox,
LinKit All can read that email and finish the sign-up. It only reads. It never deletes mail
or marks it as read.

You need a Gmail **app password**. It is not your normal password.

1. Turn on 2-Step Verification for your Google account, if it is not on already.
2. Open your Google Account, then **Security**, then **2-Step Verification**, then
   **App passwords**.
3. Create an app password and name it `LinKit`.
4. Copy the 16-character password and paste it into the wizard. Spaces are fine.
5. Press **Test and save**.

Unlock the vault first (step 7). The app password is kept in the vault.

Under **Advanced** you can change the IMAP server (default `imap.gmail.com`). Only Gmail
has been tested. Another IMAP provider that accepts app passwords may work if you enter its
server. Outlook needs a different sign-in method that is not built yet.

## 9. API keys

Some job sites share their listings through a free API: Adzuna (app ID and app key), Reed
(API key), USAJobs (API key and the email you registered with) and WhatJobs (a publisher ID
per country, written `gb=123, us=456`). Register on each site with the link on its card and
paste the key. It is optional, and every card is separate.

Unlock the vault first (step 7). The keys are kept there, encrypted, and are never shown in
full again: a saved secret appears only as its last 4 characters. To change one field, leave
the other secret fields blank and they keep their saved value. **Remove** deletes the key.

## 10. Finish

A checklist shows what is ready: profile, CV, AI provider, a search or company, and
LibreOffice. **Find jobs now** runs discover, enrich, rank and score. Nothing is applied
to yet.
