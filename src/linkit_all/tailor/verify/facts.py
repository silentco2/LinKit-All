"""Fact check on the tailored CV's final text (CLAUDE.md §2: no fabricated CV content).

The patch rules judge each edit; this reads the finished PDF as a recruiter would and compares
it with the original: every number, date, employer and job title in it must already be in the
original CV or the locked facts. Rules only, no AI. Anything new rolls the patches back.

ponytail: word heuristics on extracted PDF text. Ceilings: a new name that lands first on a
line is not seen, and a reworded word before a role ("skilled engineer" for "experienced
engineer") is refused although harmless. Both err towards sending the CV unchanged.

Logic adapted from career-ops (MIT).
"""

from collections.abc import Iterable
from itertools import pairwise
from pathlib import Path

import pymupdf

from linkit_all.tailor.patches import _is_fact, tokens

_MONTHS = frozenset(
    {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"}
)
_MONTH_NAMES = frozenset(
    {
        "january", "february", "march", "april", "june", "july", "august", "september", "sept",
        "october", "november", "december",
    }
)  # fmt: skip
# A job title is a rank and a role. A rank is judged with the word it ranks ("Senior" +
# "Engineer"), a role with the word that names its kind ("Software" + "Engineer"); the word on
# the other side is free, so "Mentored junior developers" may become "Coached junior developers".
_RANKS = frozenset(
    {
        "senior", "sr", "junior", "jr", "lead", "principal", "staff", "chief", "head", "vp",
        "vice", "deputy", "executive", "associate", "assistant", "founding", "managing",
    }
)  # fmt: skip
_ROLES = frozenset(
    {
        "engineer", "developer", "programmer", "architect", "designer", "analyst", "scientist",
        "researcher", "consultant", "specialist", "administrator", "coordinator", "technician",
        "accountant", "auditor", "teacher", "lecturer", "professor", "nurse", "pharmacist",
        "doctor", "lawyer", "editor", "writer", "recruiter", "strategist", "representative",
        "manager", "director", "supervisor", "president", "officer", "founder", "co-founder",
        "cofounder", "owner", "partner", "intern", "trainee", "lead", "head", "cto", "ceo",
        "cfo", "coo", "cio",
    }
)  # fmt: skip
# After one of these a capital letter starts a sentence or a bullet; it does not mark a name.
_STARTS = (".", "!", "?", ":", "•", "·", "●", "▪", "■", "◦", "-", "–", "—", "*", "|")  # noqa: RUF001


def pdf_text(pdf: Path) -> str:
    with pymupdf.open(pdf) as doc:
        return "\n".join(str(page.get_text()) for page in doc)


def _norm(tok: str) -> str:
    low = tok.lower()
    return low[:3] if low in _MONTHS or low in _MONTH_NAMES else low  # "January" == "Jan"


def _pairs(words: list[str]) -> set[tuple[str, str]]:
    return set(zip(["", *words], [*words, ""], strict=True))


def _has_digit(tok: str) -> bool:
    return any(c.isdigit() for c in tok)


def new_facts(
    original: str, tailored: str, locked: Iterable[str] = (), known: Iterable[str] = ()
) -> list[str]:
    """What the tailored text states that the original CV and the locked facts do not; empty
    when it is clean. `known`: extra words the user gave us (the profile's skills)."""
    locked = [" ".join(f.split()) for f in locked if f.strip()]
    src = [_norm(t) for t in tokens("\n".join([original, *locked]))]
    new = [_norm(t) for t in tokens(tailored)]
    src_words = {*src, *(k.lower() for k in known)}
    src_pairs = _pairs(src)
    found: list[str] = []

    # Numbers, metrics, years, contact details: each must already be there, as written.
    found += [t for t in new if _is_fact(t) and t not in src_words]

    for a, b in zip(["", *new], [*new, ""], strict=True):
        if (a, b) in src_pairs:
            continue
        # A date: "Mar 2021" where the CV says "Jan 2021" (both words exist, the pair is new).
        if (a in _MONTHS and _has_digit(b)) or (b in _MONTHS and _has_digit(a)):
            found.append(f"{a} {b}")
        # A job title: a rank or a role put on a word the CV does not put it on.
        elif a in _RANKS or b in _ROLES:
            found.append(f"{a} {b}".strip())

    # Locked facts (employers, titles, degrees, schools) appear exactly as often as before.
    flat_old, flat_new = " ".join(original.split()), " ".join(tailored.split())
    found += [f for f in locked if flat_old.count(f) != flat_new.count(f)]

    # An employer or any other name: a capitalised word inside a line that the CV never used.
    for line in tailored.splitlines():
        words = line.split()
        for prev, raw in pairwise(words):
            tok = "".join(tokens(raw))
            if tok[:1].isupper() and _norm(tok) not in src_words and not prev.endswith(_STARTS):
                found.append(tok)
    return list(dict.fromkeys(found))
