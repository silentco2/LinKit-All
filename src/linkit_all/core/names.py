# ruff: noqa: RUF001
"""A person's name: its parts, and the same name in the other script (Arabic or English).

Offline and without AI. `data/name_pairs.json` is arabnamer's name dictionary (see NOTICE); a name
it does not know is spelled letter by letter, and the user can correct the result in Settings.
"""

import json
import re
import string
from functools import lru_cache
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz

DATA = Path(__file__).parent.parent / "data"
Lang = Literal["ar", "en"]
_ARABIC = re.compile(r"[؀-ۿ]")
_MARKS = re.compile(r"[ً-ْٰ]")  # short vowels, which most people do not write
_SAME_LETTER = str.maketrans("أإآةى", "اااهي")
_TO_ARABIC = [
    ("sh", "ش"), ("kh", "خ"), ("th", "ث"), ("gh", "غ"), ("dh", "ذ"), ("ch", "تش"), ("ou", "و"),
    ("oo", "و"), ("ee", "ي"), ("ei", "ي"), ("ai", "اي"), ("a", "ا"), ("b", "ب"), ("c", "ك"),
    ("d", "د"), ("e", ""), ("f", "ف"), ("g", "ج"), ("h", "ه"), ("i", "ي"), ("j", "ج"), ("k", "ك"),
    ("l", "ل"), ("m", "م"), ("n", "ن"), ("o", "و"), ("p", "ب"), ("q", "ق"), ("r", "ر"), ("s", "س"),
    ("t", "ت"), ("u", "و"), ("v", "ف"), ("w", "و"), ("x", "كس"), ("y", "ي"), ("z", "ز"),
]  # fmt: skip
_TO_LATIN = str.maketrans({
    "ا": "a", "أ": "a", "إ": "e", "آ": "a", "ب": "b", "ت": "t", "ث": "th", "ج": "g", "ح": "h",
    "خ": "kh", "د": "d", "ذ": "z", "ر": "r", "ز": "z", "س": "s", "ش": "sh", "ص": "s", "ض": "d",
    "ط": "t", "ظ": "z", "ع": "a", "غ": "gh", "ف": "f", "ق": "k", "ك": "k", "ل": "l", "م": "m",
    "ن": "n", "ه": "h", "ة": "a", "و": "o", "ي": "i", "ى": "a", "ئ": "e", "ؤ": "o", "ء": "",
})  # fmt: skip


def script_of(name: str) -> Lang:
    return "ar" if _ARABIC.search(name) else "en"


def name_part(full: str, part: str) -> str:
    """Split on spaces: the first word is first, the last is last, the rest are the middle."""
    words = full.split()
    if not words:
        return ""
    middle = words[1:-1]
    return {
        "first_name": words[0],
        "last_name": words[-1] if len(words) > 1 else "",
        "middle_name": middle[0] if middle else "",  # the 2nd name only
        "middle_names": " ".join(middle),
        "third_name": words[2] if len(words) > 2 else "",  # forms with four name boxes
        "full_name": " ".join(words),
    }[part]


def _arabic_key(text: str) -> str:
    return _MARKS.sub("", text).translate(_SAME_LETTER)


@lru_cache(maxsize=1)
def _english_to_arabic() -> dict[str, str]:
    pairs: dict[str, str] = json.loads((DATA / "name_pairs.json").read_text("utf-8"))
    return pairs


def _usual(spelling: str, group: list[str]) -> tuple[float, str]:
    """Closest to the other spellings of the name, nudged to the o/e of Osama, Mohamed, Ahmed."""
    fit = sum(fuzz.ratio(spelling, other) for other in group) / len(group)
    padded = 3 * len(spelling) if len(group) > 4 else 0  # long groups list every variant
    abdel = 20 if spelling.startswith("abdel") else 0  # Abdelrahman, the usual Egyptian form
    return fit + 5 * sum(spelling.count(v) for v in "oe") - padded + abdel, spelling


@lru_cache(maxsize=1)
def _arabic_to_english() -> dict[str, str]:
    """One English spelling per Arabic name; the list has no counts, so this picks by shape."""
    spellings: dict[str, list[str]] = {}
    for english, arabic in _english_to_arabic().items():
        spellings.setdefault(_arabic_key(arabic), []).append(english)
    return {
        arabic: max(group, key=lambda c: _usual(c, group)) for arabic, group in spellings.items()
    }


def _spell(word: str, to_arabic: bool) -> str:
    if not to_arabic:
        return word.translate(_TO_LATIN)
    out, rest = "", word.lower()
    while rest:
        for latin, arabic in _TO_ARABIC:
            if rest.startswith(latin):
                out, rest = out + arabic, rest[len(latin) :]
                break
        else:  # a letter with no sound in the table (a hyphen, an accent)
            rest = rest[1:]
    return out


def translate(name: str) -> str:
    """The name in the other script. Runs of up to 3 words are tried, for "Abdel Rahman"."""
    to_arabic = script_of(name) == "en"
    table = _english_to_arabic() if to_arabic else _arabic_to_english()
    words = name.split()
    out: list[str] = []
    i = 0
    while i < len(words):
        for size in (3, 2, 1):
            run = " ".join(words[i : i + size])
            key = run.lower().replace("-", "") if to_arabic else _arabic_key(run)
            found = table.get(key) or table.get(key.replace(" ", ""))
            if i + size <= len(words) and found:
                out.append(found)
                i += size
                break
        else:
            out.append(_spell(words[i], to_arabic))
            i += 1
    return " ".join(out) if to_arabic else string.capwords(" ".join(out))


def name_in(full: str, lang: Lang | None, written: str = "") -> str:
    """The name for a form: as typed, or in `lang`, preferring what the user wrote themselves."""
    if lang is None or script_of(full) == lang or not full.strip():
        return full
    return written.strip() or translate(full)
