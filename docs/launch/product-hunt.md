# Product Hunt

**Name:** LinKit All

**Tagline** (60 characters at most): Open-source AI job search that runs on your computer

**Topics:** Open Source, Productivity, Artificial Intelligence, Hiring

**Description** (260 characters at most):

Finds jobs from 100+ job systems, ranks them against your CV for free, tailors your CV without
inventing anything, and fills in applications in your own browser. Bring your own AI, even a
local one. No telemetry. Free and open source.

**Gallery:** `docs/assets/social.png` first, then `docs/assets/demo.gif`, then screenshots of Home (a run in progress), Jobs,
Needs you and a CV red-line. Take them from the app seeded with `scripts/seed_usability.py`,
never from your real data.

**Maker comment:**

I made LinKit All after too many evenings of retyping my CV into job forms. The tools that
automated it wanted my data on their servers, or let an AI rewrite my CV with things I never
did.

LinKit All runs on your computer. Your AI (a ChatGPT or Claude plan, an API key, or a local
model) only gets your CV and job text, and the app checks every CV edit in code: no new
employers, dates, numbers or skills, and the layout must stay the same. Questions about visa,
salary or demographics never reach the AI.

It starts in Practice mode, so you can watch it fill forms before you let it submit anything.
It is young: three job systems have dedicated handlers and the rest use a general form agent
that still misses often. I publish the numbers in the README. Tell me what breaks.
