"""Text normalisation that survives evasion, plus clause-scoped negation.

Signals and weights adapted from Hackathon-HireProof (ISC) and fake-job-detector (MIT).
The normaliser is re-implemented from the ideas in HireProof's normalizer, not copied.

Two views of a text:
- `light()`: NFKC, casefold, Arabic letter variants, ASCII digits. Safe for amount parsing.
- `fold_variants()`: `light()` plus homoglyph, letter-spacing and leetspeak folding, for keyword
  matching only. Digits next to letters may be leetspeak, so never parse numbers from it.
"""

# ruff: noqa: E501, RUF001  (regex tables, Arabic and look-alike letters on purpose)

import re
import unicodedata
from bisect import bisect_left, bisect_right

# Cyrillic / Greek / Armenian look-alikes that NFKC keeps, mapped to the Latin letter they imitate.
_HOMOGLYPHS = str.maketrans(
    {
        **dict(zip("асеорхуѕіјкнвтмгԁԛѡ", "aceopxysijkhbtmrdqw", strict=True)),
        **dict(zip("αορεικνυτχβημϲ", "aopeikvutxbnmc", strict=True)),
        "ո": "n",
        "ⅼ": "l",
        "ⅰ": "i",
    }
)
_INVISIBLE = re.compile("[​-‏‪-‮⁠⁦-⁩﻿­᠎]")
_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿️⃣]")
_AR_MARKS = re.compile("[ً-ٰٟـۖ-ۭ]")  # tashkeel, dagger alef, tatweel
_AR_LETTERS = str.maketrans(
    {
        "أ": "ا",
        "إ": "ا",
        "آ": "ا",
        "ٱ": "ا",
        "ى": "ي",
        "ئ": "ي",
        "ؤ": "و",
        "ة": "ه",
        "٬": ",",
        "٫": ".",
    }
    | {chr(0x0660 + i): str(i) for i in range(10)}
    | {chr(0x06F0 + i): str(i) for i in range(10)}
)
_SPACED = re.compile(r"(?<![^\W\d_])(?:[^\W\d_][ .\-_]){3,}[^\W\d_](?![^\W\d_])")
_SPACER = re.compile(r"[ .\-_]")
# A leetspeak character: a digit touching a letter, or @/$ between letters (but an "@" that starts a
# domain, as in an email address, stays).
_LEET = re.compile(r"(?<=[a-z])[013457]|[013457](?=[a-z])|(?<=[a-z])[@$](?=[a-z])(?![\w-]+\.[a-z])")
_LEET_MAP = {"0": "o", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
_ONE_ADJACENT = re.compile(r"(?<=[a-z])1|1(?=[a-z])")
_SPACES = re.compile(r"[ \t  - 　]+")
_APOSTROPHES = re.compile("['’‘`ʼ]")


def fold_arabic(text: str) -> str:
    """Arabic only: drop tashkeel/tatweel, unify alef, yeh and teh marbuta, digits to ASCII."""
    return _AR_MARKS.sub("", text).translate(_AR_LETTERS)


def light(text: str) -> str:
    """NFKC, casefold, invisible characters and emoji removed, Arabic variants unified."""
    text = unicodedata.normalize("NFKC", text)
    if not text.isascii():
        text = fold_arabic(_EMOJI.sub("", _INVISIBLE.sub("", text)).casefold())
    else:
        text = text.casefold()
    if "'" in text:
        text = text.replace("'", "")
    if not text.isascii():
        text = _APOSTROPHES.sub("", text)
    if "  " in text or "\t" in text or not text.isascii():
        text = _SPACES.sub(" ", text)
    return text


def _strip_marks(text: str) -> str:
    if text.isascii():
        return text
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def _swap(m: re.Match[str], one: str) -> str:
    ch = m.group(0)
    return one if ch == "1" else _LEET_MAP.get(ch, ch)


def fold_light(light_text: str) -> tuple[str, ...]:
    """Matching views of text already passed through `light()`. "1" can stand for "l" or "i", so a
    text with a letter-adjacent "1" yields two views (l first); every other text yields one."""
    base = light_text.translate(_HOMOGLYPHS)
    base = _SPACED.sub(lambda m: _SPACER.sub("", m.group(0)), base)
    base = _strip_marks(base)
    ones = ("l", "i") if "1" in base and _ONE_ADJACENT.search(base) else ("l",)
    return tuple(_leet(base, one) for one in ones)


def fold_variants(text: str) -> tuple[str, ...]:
    """`fold_light(light(text))`."""
    return fold_light(light(text))


def _leet(text: str, one: str) -> str:
    # Several passes: in "f33" only the first 3 touches a letter until it has been folded.
    for _ in range(4):
        if not _LEET.search(text):
            break
        text = _LEET.sub(lambda m: _swap(m, one), text)
    return text


def fold(text: str) -> str:
    """Primary matching view (see `fold_variants`)."""
    return fold_variants(text)[0]


# ---- clause-scoped negation -------------------------------------------------------------------

_BOUNDARY = re.compile(
    r"[,;:!?\n\r|•،؛؟]+|\.(?=\s|$)|\s[-–—/]\s"
    r"|(?<!\w)(?:but|however|though|although|yet|whereas|nevertheless|لكنه?|ولكن)(?!\w)"
)
_NEGATION = re.compile(
    r"(?<!\w)[وف]?(?:no|never|not|without|dont|doesnt|wont|isnt|arent|nor|none|zero|neither|avoid|beware"
    r"|free of|لا|لن|ليس|ليست|بدون|بلا|دون|عدم|غير|لم)(?!\w)"
)
_COERCION = re.compile(
    r"(?<!\w)[وف]?(?:must|mandatory|obligatory|compulsory|cannot|can not|unable|only after|before you can"
    r"|يجب|لازم|الزامي[هة]?|اجباري[هة]?|ضروري|لا يمكن|لا تستطيع)(?!\w)"
)


class Clauses:
    """Clause boundaries of one folded text, computed lazily (only when a hit needs checking)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._starts: list[int] | None = None
        self._ends: list[int] = []

    def span(self, pos: int) -> tuple[int, int]:
        if self._starts is None:
            ms = list(_BOUNDARY.finditer(self.text))
            self._starts = [m.start() for m in ms]
            self._ends = [m.end() for m in ms]
        i = bisect_right(self._ends, pos) - 1
        start = self._ends[i] if i >= 0 else 0
        j = bisect_left(self._starts, pos)
        end = self._starts[j] if j < len(self._starts) else len(self.text)
        return start, end

    def clause(self, pos: int) -> str:
        s, e = self.span(pos)
        return self.text[s:e]

    def negated(self, start: int) -> bool:
        """True when a negation precedes `start` in its clause and nothing in the clause coerces:
        "no fee" is negated; "you must pay the fee" and "cannot start without the fee" are not."""
        s, e = self.span(start)
        if _COERCION.search(self.text, s, e):
            return False
        return _NEGATION.search(self.text, s, start) is not None
