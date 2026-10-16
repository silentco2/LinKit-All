# Privacy and security

LinKit All is built so that your CV, answers and passwords stay on your computer.

## What is stored, and where

Everything lives in one data folder, in your user data location. You can choose another
place with `LINKIT_DATA_DIR`.

| OS | Default folder |
|---|---|
| Windows | `%LOCALAPPDATA%\linkit-all` |
| macOS | `~/Library/Application Support/linkit-all` |
| Linux | `~/.local/share/linkit-all` |

| Inside | Holds |
|---|---|
| `linkit.db` | Profile, settings, jobs and their history, answer bank, Action Center items, vault (encrypted) |
| `cvs/` | Your base CV, and the original upload in `cvs/original/` |
| `tailored/` | The tailored CV and PDF for each job |
| `applications/` | Screenshots from application runs, and traces of failed ones |
| `browser/` | One Chrome profile per job site (cookies, sessions) |
| `models/` | The downloaded ranking model |
| `tools/` | The minimal LibreOffice, if you installed it |
| `logs/` | `linkit.log` (rotated at 10 MB, 5 files kept) |

Screenshots of filled forms contain your personal details. They never leave the folder, but
treat the folder as private. To remove everything, close the app and delete it.

## What your AI provider sees

Only the provider you picked ever receives your text. With a local model, nothing leaves your
computer. These are the cases:

| Task | What is sent |
|---|---|
| Scoring | The first 6,000 characters of your CV, your search preferences, and a short summary of each job (title, company, location, work mode, first 1,500 characters of the description) |
| Tailoring | The CV text in numbered segments, your skills and locked facts, and the job description |
| Answer drafts and cover letters | The question, your CV, and non-sensitive profile facts (name, location, current role, years of experience, notice period, links, relocation) |
| Generic form agent | The form controls of the current page, its text, and a brief of the job |
| Careers pages without structured data | Short excerpts of job pages, 10 per call |
| Verification emails | Only when pattern matching finds no code or link: the email text, up to about 4,000 characters |

**Never sent to the AI:** answers to [sensitive questions](action-center.md#sensitive-questions)
(visa, salary, demographics, legal), your passwords, your email app password, and anything in
the vault.

With Codex CLI or Claude CLI, the prompt goes through that tool to your own account. LinKit All
runs them in an empty folder with their own tools off.

## Other network traffic

LinKit All talks to: the job sources you list, the application sites you apply to, your AI
provider, your mail server (only if you connect email), and Hugging Face, once, to
download the ranking model. It also fetches `robots.txt` files. That is all.

**There is no telemetry, analytics or crash reporting.** These docs use system fonts and no
trackers either.

## The local web page

The server listens on `127.0.0.1` only. It rejects requests whose `Host` is not a loopback
name (a guard against DNS rebinding), and it rejects writes and WebSockets that come from
another website. Screenshot and file downloads are only served from inside the data folder.
Other people on your network cannot reach it.

## The vault

The vault keeps site passwords (made by LinKit All) and your email app password.

- Each secret is encrypted separately with **AES-GCM**. The site and username are bound to the
  ciphertext, so an entry cannot be swapped for another.
- The key comes from your passphrase with **Argon2id** (3 passes, 64 MiB of memory, 4 lanes).
  The settings are stored with the vault, so they can be raised later.
- The passphrase is at least 8 characters and **cannot be recovered**.
- While unlocked, the key is held in memory. If you choose **Remember on this computer**, it is
  also kept in your operating system's keyring, so the vault opens by itself next time. Turn that
  off on a shared computer. **Lock** removes it from the keyring.
- Showing a password, or exporting the vault, asks for your passphrase again. An export is a
  plain **unencrypted** JSON file. Keep it safe or delete it.

## Logs

Logs go to the console and to `logs/linkit.log`. They hold ids, counts and states. Secrets
that look like `password=...`, tokens, `Bearer ...` values and `sk-` style keys are masked
before they are written. CV text, form answers, email bodies and passwords are not passed to
the logger at all. The masking is pattern based, so do not paste secrets into free-text fields
you do not want in logs.
