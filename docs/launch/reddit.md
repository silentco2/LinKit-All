# Reddit

Read each subreddit's rules before posting; several allow self-promotion only on set days or
in a weekly thread. Post in one sub a day, reply to comments for the first few hours, and never
ask for upvotes.

## r/opensource and r/selfhosted

**Title:** I built an open-source job search tool that runs locally: finds jobs, tailors your CV without inventing anything, fills in applications

**Body:**

LinKit All is a local app (Python + a web page on 127.0.0.1) that:

1. finds jobs from 100+ applicant tracking systems' public APIs, LinkedIn/Indeed via JobSpy,
   regional boards and any careers page;
2. ranks them against your CV with a local embedding model, and flags scams and ghost jobs
   offline;
3. tailors your CV with small word edits that are checked in code: no new employers, titles,
   dates, numbers or skills, and the PDF layout must not change;
4. fills in applications in your own Chrome/Edge/Brave, in Practice mode until you switch it.

Bring your own AI: ChatGPT/Claude plan via their CLIs, an API key, or Ollama/LM Studio for
fully local. No telemetry, no account, AGPL-3.0.

Limits: dedicated form handlers only for Greenhouse, Lever and Ashby; the generic form agent
is still weak (numbers in the README). LinkedIn/Indeed/Glassdoor are never automated; a
browser extension fills them while you click.

`uv tool install linkit-all` → `linkit`. Repo: https://github.com/silentco2/LinKit-All

## r/Python

**Title:** LinKit All: a FastAPI + Playwright app that automates job applications without letting the AI rewrite your CV

**Body:**

Some parts that may interest Python people:

- Playwright attaches over CDP to the user's installed Chrome, launched without automation
  flags, one persistent profile per site.
- CV tailoring edits DOCX runs in place with python-docx + lxml (body, tables, text boxes,
  headers), renders through LibreOffice headless, and compares pages with SSIM before
  accepting the patch set.
- LLM output is always a Pydantic model; the CLI adapters run `codex exec --json` and
  `claude -p` in an empty temp dir with their tools disabled.
- A seeded fake job board (`linkit bench`) measures dedupe, scam/ghost detection, ranking and
  the tailoring guard; CI runs it on Windows, macOS and Linux.

Repo: https://github.com/silentco2/LinKit-All. Feedback on the architecture welcome.

## r/cscareerquestions (only where the rules allow tools)

**Title:** Free, open-source tool that applies to jobs for you without sending your data anywhere

**Body:** Use the r/opensource text, and lead with the privacy point and Practice mode.
