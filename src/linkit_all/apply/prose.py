"""Rules-only guard against phrasing that reads as machine-written, for every piece of prose the
AI writes for the user (cover letters, emails, free-text answers). No AI: a fixed list of
high-precision giveaways, each with a plain replacement, and dashes used between clauses.
Recruiters who spot an automated application tend to discard it, and an auto-apply tool sends
many, so the replacements are applied to every text after one retry (`retry_note`) at most.
Idea from Job-Ops' "Stop Slop" option (docs/job-ops-borrow-plan.md, A4); the list is our own."""

import re
from functools import partial

# Whole sentences that carry nothing: dropped.
_FILLER = re.compile(
    r"[^.!?\n]*\b(?:i hope (?:this|my) (?:email|message|note|letter) finds you well"
    r"|in today'?s (?:fast-paced|ever-changing|rapidly evolving|competitive)\b)"
    r"[^.!?\n]*[.!?]?[ \t]*",
    re.IGNORECASE,
)
# (pattern, plain replacement); the replacement keeps a capital at the start of a sentence.
_SWAPS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p, re.IGNORECASE), r)
    for p, r in (
        (r"\bI am writing to express my (?:strong |keen |sincere )?interest in\b",
         "I am applying for"),
        (r"\bI(?: am|'m) (?:so |very |truly |really )?(?:excited|thrilled|delighted|eager) to\b",
         "I would like to"),
        (r"\b(?:deeply |truly )?passionate about\b", "keen on"),
        (r"\bdelve into\b", "look into"),
        (r"\bdelving into\b", "looking into"),
        (r"\bleverag(?:es|e|ing|ed)\b", "use"),
        (r"\butili[sz](?:es|e|ing|ed)\b", "use"),
        (r"\bis a testament to\b", "shows"),
        (r"\bin the realm of\b", "in"),
        (r"\bunwavering\s+", ""),
        (r"\bdynamic team\b", "team"),
        (r"(?m)(?:^|(?<=[.!?] ))(?:Moreover|Furthermore|Additionally),[ \t]*", "Also, "),
    )
)  # fmt: skip
_TENSE = {"leverages": "uses", "leveraging": "using", "leveraged": "used", "utilizes": "uses",
          "utilises": "uses", "utilizing": "using", "utilising": "using", "utilized": "used",
          "utilised": "used"}  # fmt: skip
# A dash between words: an em dash, or an en dash or hyphen with spaces round it. Ranges
# ("2019-2021" with an en dash), hyphenated words and list bullets at the start of a line stay.
_DASH = re.compile(r"(?<=\S)[ \t]*—[ \t]*(?=\S)|(?<=\S)[ \t]+[–-][ \t]+(?=\S)")  # noqa: RUF001


def tells(text: str) -> list[str]:
    """The giveaway phrases in `text`, as written there; [] when it reads clean."""
    found = [m.group(0).strip() for m in _FILLER.finditer(text)]
    found += [m.group(0).strip() for pattern, _ in _SWAPS if (m := pattern.search(text))]
    if _DASH.search(text):
        found.append("—")
    return found


def retry_note(text: str) -> str:
    """Prompt text that asks for a rewrite without the giveaways; "" when there are none."""
    if not (found := tells(text)):
        return ""
    listed = "; ".join(f'"{f}"' for f in dict.fromkeys(found))
    return (
        f"\n\nYour previous answer used stock phrases that read as machine-written: {listed}. "
        "Write it again in plain, direct words without them, and do not use dashes between clauses."
    )


def _swap(m: re.Match[str], plain: str) -> str:
    word = m.group(0)
    plain = _TENSE.get(word.lower(), plain)
    return plain[:1].upper() + plain[1:] if word[:1].isupper() and plain else plain


def clean(text: str) -> str:
    """`text` with filler sentences dropped, giveaways swapped and clause dashes made commas."""
    text = _FILLER.sub("", text)
    for pattern, plain in _SWAPS:
        text = pattern.sub(partial(_swap, plain=plain), text)
    text = _DASH.sub(", ", text)
    text = re.sub(r"(?m)[ \t]+$", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
