# Troubleshooting

Start with:

```bash
linkit doctor
```

It shows which tools are found. Logs are in `logs/linkit.log` inside your
[data folder](privacy.md#what-is-stored-and-where). Raise the detail with
`LINKIT_LOG_LEVEL=DEBUG`.

## LibreOffice not found

Tailoring and applying need LibreOffice to make the PDF. `linkit doctor` shows `MISSING`.

- Install it from [libreoffice.org](https://www.libreoffice.org/download/), or install the
  minimal bundle with `linkit install-libreoffice <zip>`. See [Install](install.md#libreoffice).
- On Windows it is also found in `Program Files` and `LocalAppData`. On macOS, in
  `/Applications/LibreOffice.app`. Otherwise `soffice` or `libreoffice` must be on your PATH.
- If you installed the bundle but it is not used, check that
  `<data folder>\tools\libreoffice\program\soffice.exe` exists.
- When LibreOffice is missing, the Apply stage stops early with a message. Your jobs keep their
  state. Fix it and run Apply again.

## Chrome and the browser profile

- Applying needs Google Chrome (`linkit doctor` shows it as optional until you apply). LinKit All
  does not download a browser.
- Each job site has its own profile in `browser/<site>` inside the data folder. If a site
  behaves strangely (stuck login, odd cookies), close LinKit All and delete that site's folder.
  You lose its saved login only.
- If the browser window does not appear, check that *Hide the browser window (headless)* is
  off in the wizard's Applying step.
- A page that keeps showing a CAPTCHA is not fixed by LinKit All. See [CAPTCHAs](applying.md#captchas).

## AI problems

**Check the connection:**

```bash
linkit ai-check
```

- **"not installed" or a sign-in error.** Install the Codex CLI or Claude Code and sign in **in
  your own terminal** first. LinKit All calls the tool, but you sign in once yourself.
- **Run paused with "AI usage limit".** Your plan's limit was reached. Nothing is lost. Start the
  run again later. Scored jobs stay scored, and the rest are scored next time. To use less of
  your plan, lower *Jobs sent to the AI per run* in the Filters step.
- **Invalid output errors with a small local model.** Answers are retried up to two more times. A
  larger model usually fixes it.
- **A model name is required.** For an API key (`litellm`), set `LINKIT_MODEL`, for example
  `openai/gpt-5-mini`.
- **Slow.** CLI providers run one call at a time. You may raise `LINKIT_LLM_CONCURRENCY` up to 3.

## Jobs and runs

- **No jobs found.** Look at the end of the run for skipped entries and errors. Check that your
  searches match job titles, and that `posted_within_days` is not too small.
- **LinkedIn returns nothing.** It limits automated searches quickly. A failed search is not
  marked done, so starting the run again retries it. Wait a while first.
- **Wuzzuf and Forasna are slow.** They ask for one request per 10 seconds, and only jobs whose
  address contains every word of a search are fetched. Forasna addresses are mostly Arabic.
- **A careers page is "unsupported".** It needs a real browser to show its jobs, or it answers with
  a bot check. Use the company's ATS link if you can find it.
- **The first rank is slow.** The ranking model (about 220 MB) is downloaded once.
- **A job was dry-run but is not picked again.** That is on purpose, so one job is not filled in
  over and over. Turn on live applying to apply for real.
- **A job I expected is missing.** Open the **Jobs** page and look at its history. A filtered job
  shows the rule that dropped it.

## CV problems

- **"This file is not a Word file."** Upload a real `.docx`, `.odt`, `.pdf` or `.tex`, up to 10 MB.
- **A PDF CV looks wrong.** PDF conversion is lossy. Use your original Word file if you have it,
  or fix the converted CV before approving.
- **Tailoring "rolled back".** The layout check failed (page count or look changed), so your
  original CV was used. That is working as designed. See
  [Verify and roll back](tailoring.md#verify-and-roll-back). Lowering `LINKIT_TAILOR_MIN_SSIM` is
  possible but not recommended.
- **LaTeX CV will not compile.** Install Tectonic. Keep the CV as one file, without `\input`.

## Vault and email

- **Forgot the vault passphrase.** It cannot be recovered. Create a new vault. Site passwords
  that were only in the old vault are lost, so you would sign in to those sites by hand or reset
  their passwords.
- **"Keyring unavailable" in the log.** The operating system keyring is missing or locked. The
  vault still works, but is not remembered between restarts. Unlock it each time.
- **Email test fails.** Use a Gmail **app password**, not your normal password, with 2-Step
  Verification on. Check that IMAP is allowed and that the address is right. See
  [the Email step](setup.md#8-email).

## Windows notes

- **The console shows garbled letters or an encoding error** (code page 1256 and similar). Tell
  Python to use UTF-8 before you run commands that print Arabic or special symbols:

    ```powershell
    $env:PYTHONIOENCODING = "utf-8"
    ```

    You can also run `chcp 65001`.
- **Run `linkit` from a normal terminal.** Programs installed from the Microsoft Store (packaged
  apps) can have their `AppData` writes redirected to a private folder. If a tool you installed
  that way can't see LinKit All's data folder, install and run everything from a regular
  terminal, or set `LINKIT_DATA_DIR` to a plain folder such as `D:\linkit-data`.
- **Port 8765 is busy.** Use `linkit serve --port 9000`.
- **Long paths.** Keep `LINKIT_DATA_DIR` short, for example `C:\linkit-data`.

## Still stuck?

Run the failing step on its own, for example `linkit run rank`, and read the message. When you ask
for help, include the output of `linkit doctor` and the relevant lines of `logs/linkit.log`.
Passwords and tokens are masked in logs, but check before you share.
