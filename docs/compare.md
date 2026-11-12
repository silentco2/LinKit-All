---
title: "LinKit All vs AIHawk vs ApplyPilot: open-source auto-apply"
description: "A sourced comparison of three open-source AI job application tools: how they run, which AI they need, job sites, CV tailoring, sensitive questions, telemetry."
---

# Compared with AIHawk and ApplyPilot

AIHawk and ApplyPilot are the two best-known open-source AI job application tools. This page
compares them with LinKit All using only what each project says about itself. Facts about the
other two come from their READMEs, read on 2026-11-12. They change often, so check the links
before you rely on a row. "Not stated" means the README does not say. It does not mean the
tool lacks the feature.

| | LinKit All | [AIHawk][aihawk] | [ApplyPilot][applypilot] |
|---|---|---|---|
| License | AGPL-3.0-or-later | MIT | AGPL-3.0 |
| How you use it | Local web page, plus a `linkit` command line | Started from a terminal script; applies in a Firefox window | Command line, plus an HTML results dashboard |
| AI it works with | ChatGPT plan (Codex CLI), Claude plan (Claude Code), API keys through LiteLLM, local models (Ollama, LM Studio) | A key from OrcaRouter; others not stated | A Gemini key for scoring and tailoring (OpenAI and local models also supported); auto-apply needs the Claude Code CLI |
| Where it finds jobs | 100+ applicant tracking systems' public APIs, LinkedIn, Indeed, Glassdoor, ZipRecruiter, Google and Bayt through JobSpy, regional boards, any careers page, Telegram channels | "37 public sources" | Indeed, LinkedIn, Glassdoor, ZipRecruiter and Google Jobs through JobSpy, about 48 Workday portals, 30+ career sites |
| Submits for you | Only after you switch from Practice mode to Applying for real; each submit waits for your OK unless you turn that off | Yes, once you pick the jobs and confirm | Yes; a dry-run option fills forms without submitting |
| CV per job | Small word-level edits to your own file; layout kept, numbers, dates and listed facts locked | Not stated | Rewritten by AI per job, with listed facts kept |
| Cover letter | Only when the form has a field for one | Not stated | Generated per job |
| Sensitive questions (visa, salary, demographics) | Never sent to the AI: answered from your profile or left for you | Not stated | Defaults stored in the profile; screening questions are answered with AI |
| LinkedIn, Indeed, Glassdoor | Never driven; a browser extension fills them while you press Submit | Not stated | Read through JobSpy; applying not stated per site |
| Accounts on job sites | Created when needed, with a generated password in an encrypted local vault | Not stated | Not stated |
| Telemetry | None | Usage events sent to PostHog | Not stated |

[aihawk]: https://github.com/feder-cr/Jobs_Applier_AI_Agent
[applypilot]: https://github.com/Pickle-Pixel/ApplyPilot

## Where LinKit All is weaker

- Only three sites have their own form handlers (Greenhouse, Lever and Ashby). Every other
  site goes through a general AI form agent, which finished none of its 12 postings in the
  first [scorecard](scorecard.md).
- Real submitting has been tried only in a few applications that were watched by hand.
- It is young. Both other projects have far more users and stars on GitHub.

## Which one to pick

- You want full control of what is sent, sensitive answers kept away from the AI, and your CV
  layout untouched: LinKit All.
- You want the largest community and the most press coverage: AIHawk.
- You want a command-line tool that rewrites your CV and writes a cover letter for every job,
  with a free Gemini key: ApplyPilot.

Spotted a mistake about another project? [Open an issue](https://github.com/silentco2/LinKit-All/issues)
with a link to the source and it will be fixed.
