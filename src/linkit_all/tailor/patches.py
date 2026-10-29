"""AI patch model and the rules that reject unsafe patches (CLAUDE.md §2, §5.4)."""

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from pydantic import BaseModel


class Patch(BaseModel):
    segment_id: int
    old_text: str
    new_text: str
    reason: str = ""


class PatchList(BaseModel):
    patches: list[Patch]


@dataclass
class Rules:
    locked_facts: list[str]
    allowed_terms: set[str]  # lowercase words from the CV and the profile's skill list
    max_growth: float = 0.10
    max_word_change: float = 0.15


@dataclass
class Plan:
    accepted: list[Patch] = field(default_factory=list)
    rejected: list[tuple[Patch, str]] = field(default_factory=list)


# Arabic blocks: base, Supplement, Extended-A, Presentation Forms-A and -B (AI never writes these)
_ARABIC = re.compile(r"[\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff\ufb50-\ufdff\ufe70-\ufeff]")


def has_arabic(text: str) -> bool:
    return _ARABIC.search(text) is not None


def mostly_arabic(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(1 for c in letters if _ARABIC.match(c)) * 2 > len(letters)


_STRIP = ".,;:!?()[]{}\"'“”‘’"  # noqa: RUF001 (Word smart quotes)
_PLAIN = re.compile("[a-z][a-z'’\\-]*")  # noqa: RUF001


def tokens(text: str) -> list[str]:
    return [t for raw in text.split() if (t := raw.strip(_STRIP))]


def vocabulary(cv_text: str, skills: list[str]) -> set[str]:
    return {t.lower() for t in tokens(cv_text + " " + " ".join(skills))}


def _is_fact(tok: str) -> bool:
    """Numbers, dates, metrics, emails, links: never added, removed or changed."""
    return (
        any(c.isdigit() for c in tok)
        or any(c in tok for c in "@%$€£")
        or "://" in tok
        or tok.lower().startswith("www.")
    )


def unlisted_terms(old_seg: str, new_seg: str, allowed: set[str]) -> list[str]:
    """New words that look like skills/names/tools and are not in the CV or skill list.

    ponytail: heuristic. Plain lowercase words pass (rephrasing); Capitalized, CamelCase,
    acronyms and symbol words (C#, Node.js) must already be known. A sentence-initial word
    passes only as a lowercase -ed/-ing verb. Ceiling: lowercase-written tool names
    ("kubernetes") slip through; add a skills dictionary if that shows up in practice.
    """
    old = {t.lower() for t in tokens(old_seg)}
    words = new_seg.split()
    found = []
    for i, raw in enumerate(words):
        tok = raw.strip(_STRIP)
        if not tok or tok.lower() in old or tok.lower() in allowed:
            continue
        initial = i == 0 or words[i - 1].endswith((".", "!", "?", ":"))
        check = tok[0].lower() + tok[1:] if initial else tok
        if (initial and not check.endswith(("ed", "ing"))) or not _PLAIN.fullmatch(check):
            found.append(tok)
    return found


def violation(orig_seg: str, new_seg: str, rules: Rules) -> str | None:
    """Why `new_seg` may not replace `orig_seg` (the untouched original), or None."""
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


def changed_words(old: str, new: str) -> int:
    a, b = old.split(), new.split()
    ops = SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in ops if tag != "equal")


def plan_patches(segments: dict[int, str], patches: list[Patch], rules: Rules) -> Plan:
    """Accept patches in order while every rule and the total word-change cap hold."""
    plan = Plan()
    current = dict(segments)
    budget = rules.max_word_change * sum(len(t.split()) for t in segments.values())
    used = 0
    for p in patches:
        seg = current.get(p.segment_id)
        reason: str | None
        cost = 0
        if seg is None:
            reason = "unknown segment"
        elif not p.old_text or seg.count(p.old_text) != 1:
            reason = "old_text must appear exactly once in the segment"
        elif p.new_text == p.old_text:
            reason = "no change"
        elif has_arabic(p.new_text):
            reason = "new_text contains Arabic script (the AI writes English only)"
        elif mostly_arabic(seg):
            reason = "segment is written in Arabic (only English segments may be edited)"
        elif any(c in p.new_text for c in "\t\r\n"):
            reason = "new_text contains a tab or line break"
        else:
            new_seg = seg.replace(p.old_text, p.new_text, 1)
            reason = violation(segments[p.segment_id], new_seg, rules)
            cost = changed_words(p.old_text, p.new_text)
            if reason is None and used + cost > budget:
                reason = f"total word-change cap of {rules.max_word_change:.0%} reached"
        if reason:
            plan.rejected.append((p, reason))
            continue
        used += cost
        current[p.segment_id] = new_seg
        plan.accepted.append(p)
    return plan
