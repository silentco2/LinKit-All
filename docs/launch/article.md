---
title: "How I stopped an AI from lying on my CV: a patch-based tailoring guard"
tags: python, ai, opensource, career
canonical: (set to the dev.to URL once published)
---

# How I stopped an AI from lying on my CV

I built [LinKit All](https://github.com/silentco2/LinKit-All) for my own job hunt: an
open-source app that finds jobs, ranks them against my CV, tailors the CV for each job, and
fills in the applications on my own computer.

The tailoring step scared me most. Ask a language model to "tailor this CV for this job" and
it will happily turn "mentored two developers" into "led a team of five", add a tool you have
never touched, or round 3 years up to 5. Each edit reads well. Each one is a lie with your name
on it.

So the model in LinKit All is not allowed to write a CV. It is only allowed to propose patches,
and plain code decides which patches survive.

## Patches, not rewrites

The CV is split into numbered text segments (a bullet, a line of a heading). The model gets the
job description and the segments, and must answer with JSON:

```json
[{"segment_id": 12, "old_text": "built REST APIs", "new_text": "built REST APIs for payments", "reason": "the job is in payments"}]
```

Nothing else is accepted. The app writes accepted patches back into the user's own Word,
LaTeX or OpenDocument file, keeping the formatting of each run, so the layout never changes.

## The rules a patch must pass

Every patch is checked against the untouched original segment. It is refused when:

1. **It touches a locked fact.** Employers, titles, degrees and schools from the CV are locked
   automatically. If a locked string appears a different number of times after the patch, it's
   out.
2. **It changes a number, date, metric or contact detail.** Any token with a digit, `@`, `%`,
   a currency sign, a link, or a number word ("eight", "dozens", "doubled") must be the same
   before and after. "eight years" to "ten years" is caught the same way as "8" to "10".
3. **It adds a term you don't have.** New words that look like names or tools (capitalized,
   CamelCase, acronyms, `C#`, `Node.js`) must already be in your CV or skill list. Words that
   claim a bigger role ("led", "managed", "senior", "founded", "award") are refused however
   they are written.
4. **It grows the segment by more than 10%**, or pushes the total change past 15% of the CV's
   words.
5. **It breaks the format**: a line break, Arabic text in an English edit, or `old_text` that is
   not in the segment exactly once.

Here is the core, trimmed:

```python
def violation(orig_seg: str, new_seg: str, rules: Rules) -> str | None:
    for fact in rules.locked_facts:
        if orig_seg.count(fact) != new_seg.count(fact):
            return f"changes locked fact {fact!r}"
    if Counter(filter(_is_fact, tokens(orig_seg))) != Counter(filter(_is_fact, tokens(new_seg))):
        return "changes or adds a number, date, metric or contact detail"
    if terms := unlisted_terms(orig_seg, new_seg, rules.allowed_terms):
        return f"adds terms not in your CV or skills: {', '.join(terms)}"
    if len(new_seg) > len(orig_seg) * (1 + rules.max_growth):
        return f"grows the segment by more than {rules.max_growth:.0%}"
    return None
```

After the patches are applied, the file is rendered to PDF and checked again: same page count,
a pixel diff against the original within tolerance, and the text still extracts. Any failure
rolls the patches back. The user sees every change in a red-line view.

## Did it work?

I planted 25 edits: 6 honest ones and 19 that must be refused (a changed employer, date, metric
or email, an inflated title, an unlisted tool, a bigger role, and 4 that break formatting).
Rules alone refused **17 of the 19** and accepted all 6 honest edits.

The 2 that got through are the honest limit of a word list: a tool the rules don't know, written
in lowercase, and a bigger role said in other words ("ran the team"). That's a small test I wrote
myself, so read it as "the pieces behave as designed", not a guarantee.

## What I removed

An earlier version also asked a second AI call to judge each edit. I removed it before 1.0, so
what ships is rules only, and the numbers above are rules only. <!-- Maintainer: add your reason
in one sentence, or delete this section. --> Rules are boring, fast, free and easy to read,
which matters when the thing they protect is your name.

## Try it

```bash
uv tool install linkit-all
linkit
```

It starts in Practice mode: it fills forms but never presses Submit. Works with a ChatGPT or
Claude plan, an API key, or a local model through Ollama.

Code: https://github.com/silentco2/LinKit-All · The guard: `src/linkit_all/tailor/patches.py`

If it saves you an application, a ⭐ helps other job seekers find it.
