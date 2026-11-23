---
title: "ApplyPilot alternative: LinKit All, open-source AI auto-apply with a web UI"
description: "Looking for an ApplyPilot alternative? How LinKit All differs from ApplyPilot: which AI it needs, CV tailoring, sensitive questions, cover letters and how you run it."
---

# An ApplyPilot alternative

[ApplyPilot][applypilot] is an open-source command-line tool that scores jobs, rewrites your CV
and applies. LinKit All reuses some of its code (see [NOTICE][notice]). Facts about ApplyPilot
come from its README, read on 2026-11-12. "Not stated" means the README does not say. It does
not mean the tool lacks the feature.

| | LinKit All | ApplyPilot |
|---|---|---|
| License | AGPL-3.0-or-later | AGPL-3.0 |
| How you use it | Local web page, plus a `linkit` command line | Command line, plus an HTML results dashboard |
| AI it works with | ChatGPT plan (Codex CLI), Claude plan (Claude Code), API keys, local models (Ollama, LM Studio) | A Gemini key for scoring and tailoring (OpenAI and local models also supported); auto-apply needs the Claude Code CLI |
| Where it finds jobs | 295 sources: 100+ applicant tracking systems' public APIs, LinkedIn, Indeed, Glassdoor through JobSpy, regional boards, any careers page | Indeed, LinkedIn, Glassdoor, ZipRecruiter and Google Jobs through JobSpy, about 48 Workday portals, about 30 career sites |
| CV per job | Small word-level edits to your own file; layout kept, facts locked | Rewritten by AI per job, with listed facts kept |
| Cover letter | Only when the form has a field for one | Generated per job |
| Sensitive questions | Never sent to the AI: answered from your profile or left for you | Defaults stored in the profile; screening questions are answered with AI |
| Telemetry | None | Not stated |

## When LinKit All fits better

- You want a web page to watch and steer the run, not only a command line.
- You want your own CV file kept, with a few words changed per job instead of a rewrite.
- You want sensitive questions never sent to the AI.

## When ApplyPilot fits better

- You want a command-line tool that rewrites your CV and writes a cover letter for every job,
  with a free Gemini key.

Full three-way comparison, with AIHawk and where LinKit All is weaker: [Compared with AIHawk and
ApplyPilot](index.md).

[applypilot]: https://github.com/Pickle-Pixel/ApplyPilot
[notice]: https://github.com/silentco2/LinKit-All/blob/main/NOTICE
