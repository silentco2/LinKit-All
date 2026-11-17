"""The years of experience a job description asks for, read by rules only (no AI).

A title says little about this ("Lead" roles ask for four years, plain "Analyst" roles for
ten), so the figure is read from the description, sentence by sentence:

1. Find each "N years" mention: digits or words, "N+", "at least N", ranges ("3-5",
   "between 3 and 5"), Arabic ("خبرة 5 سنوات", "٣ سنوات", "سنتين").
2. Keep the ones about the candidate's experience: not age, company history, contract terms,
   degree length ("4-year degree"), time windows, ceilings ("up to 5 years") or other people.
3. Tag each one required / preferred (nearest cue in the sentence, else the section heading
   above it) and overall / skill ("3 years of experience with SQL") / degree substitute / sub.
4. The gating figure is the LOWEST required overall floor: the most lenient honest reading.

A wrong drop hides a real job; a wrong keep costs one glance. So `confident` (the only state
that may drop a job) is False for preferred-only and per-skill figures, for a bar with an
"equivalent combination" route, and for a bar under a heading this parser does not know.

Logic adapted from career-ops (MIT).
"""

import re
from dataclasses import dataclass
from typing import Literal

Kind = Literal["required", "preferred", "skill"]
_Section = Literal["required", "preferred", "unclear"]

_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}  # fmt: skip
_NUM = rf"(?:\d{{1,2}}(?:\.\d)?|{'|'.join(_WORDS)})"
_RESTATED = r"(?:\s*\(\s*\d{1,2}\s*\+?\s*\))?"  # "five (5)"
_MENTION = re.compile(
    rf"\b(?P<between>between\s+)?(?P<a>{_NUM}){_RESTATED}(?:\s*\+|[\s-]*plus\b)?"
    rf"(?:\s+or\s+(?:more|greater))?"
    rf"(?:\s*(?P<join>-|\u2013|\u2014|to|and)\s*(?P<b>{_NUM}){_RESTATED}\+?)?"
    rf"[\s-]*(?:years?|yrs?)\b",
    re.I,
)
# What may follow "years" for the mention to be about experience.
_TRAIL_OK = re.compile(
    r"^(?:'s|')?\s*\+?\s*(?:of\b|in\b|as\b|experience|exp\b|working|professional|relevant|related|"
    r"hands|industry|work\b|minimum|required|preferred|or more|total|prior|proven|"
    r"(?:[\w/&-]+\s+){1,3}(?:experience|exp)\b|[,;:.()]|$)",
    re.I,
)
_TRAIL_BARE = re.compile(r"^(?:'s|')?\s*(?:[,;:.)]|$)")  # "5+ years." needs experience named
_TRAIL_NOT = re.compile(
    r"^(?:'s|')?\s*of\s+(?:age|college|university|school|schooling|education|study|studies|"
    r"service|history|data|operations?|growth)\b",
    re.I,
)
_WINDOW_LEAD = re.compile(
    r"\b(?:within|after|every|per|(?:the\s+)?(?:first|next|last|past)|in the|for the|over the|"
    r"aged?|age of)\s*$",
    re.I,
)
_CEILING_LEAD = re.compile(
    r"\b(?:up to|less than|fewer than|no more than|not more than|under|at most|maximum of|"
    r"max(?:imum)?\.?)\s*$",
    re.I,
)
_CEILING_TRAIL = re.compile(
    r"^(?:'s|')?\s*(?:of\s+)?(?:[\w/&-]+\s+){0,4}?(?:or (?:less|fewer)|maximum|max\b|at most)",
    re.I,
)
_OTHERS_LEAD = re.compile(
    r"\b(?:engineers|experts|colleagues|peers|leaders|mentors|teammates|team members|"
    r"specialists|founders|people|analysts|developers)\s+(?:with|who have|having)\s+"
    r"(?:over\s+|more than\s+)?$",
    re.I,
)
_NOT_ABOUT_YOU = re.compile(
    r"\b(?:year[- ]over[- ]year|years? old|years? of age|founded|anniversary|in business|"
    r"vest(?:s|ed|ing)?\b|contract (?:term|length|duration)|fixed[- ]term|warranty|"
    r"parental leave|alongside|learn from|mentored by|led by)\b",
    re.I,
)
_COMPANY_VOICE = re.compile(r"\b(?:[Ww]e|[Ww]e've|[Ww]e're|[Oo]ur)\b")
_CANDIDATE_VOICE = re.compile(
    r"\b(?:you|your|candidate|applicant|required|requirements?|minimum|must|should|ideal(?:ly)?|"
    r"qualif\w*|looking for|seeking|need)\b",
    re.I,
)
_CANDIDATE_HAS = re.compile(
    r"\byou(?:'ve| have| bring|'ll (?:need|have)| will (?:need|have)| should have| must have)\b",
    re.I,
)
_PREFERRED = re.compile(
    r"\b(?:prefer(?:red|ably|ence)?|nice[- ]to[- ]have|bonus|"
    r"(?:a|is a|are a) (?:big |strong )?plus|ideally|desired|desirable|"
    r"advantage(?:ous)?|not required)\b",
    re.I,
)
_PREFERRED_END = re.compile(
    r"\b(?:preferred|desired|desirable|a (?:big |strong )?plus|nice[- ]to[- ]have|"
    r"advantageous)\W*$",
    re.I,
)
_REQUIRED = re.compile(
    r"\b(?:require[ds]?|requirements?|minimum|must|at least|mandatory|essential|need(?:ed|s)?)\b",
    re.I,
)
_SKILL_TRAIL = re.compile(
    r"^(?:'s|')?\s*\+?\s*(?:of\s+)?(?:(?:hands[- ]on|direct|professional|practical|relevant|"
    r"production|commercial)\s+)?(?:experience\s+)?(?:with|using|programming|coding|writing)\b"
    r"(?!\s+(?:an?\s+|the\s+)?(?:relevant\s+)?(?:degree|bachelor|master|mba|ph\.?d|bsc|msc))",
    re.I,
)
_DEGREE_OR_LEAD = re.compile(
    r"\b(?:degree|bachelor'?s?|diploma|bsc|b\.?s\.?|b\.?a\.?)\b[^.;]{0,40}\bor\s+(?:an?\s+)?"
    r"(?:equivalent\s+)?(?:at least\s+|a minimum of\s+)?$",
    re.I,
)
_DEGREE_SUB_TRAIL = re.compile(
    r"^[^.;]{0,50}\b(?:in lieu of|instead of|in place of|without a degree)"
    r"|^(?:'s|')?\s*(?:of\s+)?(?:\w+\s+){0,2}?equivalent\b",
    re.I,
)
_SUB_LEAD = re.compile(
    r"\b(?:including|incl\.?|of which|of those|with at least)\s*(?:at least\s+)?$", re.I
)
_EQUIVALENT = re.compile(
    r"\bequivalent combination\b"
    r"|\bcombination of (?:education|training) and (?:work )?experience\b",
    re.I,
)
_NO_EXPERIENCE = re.compile(
    r"\bno (?:prior |previous )?(?:work |professional )?experience (?:is )?"
    r"(?:required|necessary|needed)\b",
    re.I,
)
_PREFERRED_HEADING = re.compile(
    r"\b(?:prefer|nice[- ]to[- ]have|good[- ]to[- ]have|bonus|desir|plus\b|ideal|stand out)", re.I
)
_REQUIRED_HEADING = re.compile(
    r"\b(?:require|minimum|basic|must|qualif|what you(?:'ll)? (?:need|bring)|you (?:have|bring)|"
    r"looking for|about you|who you are|experience|skills)|المتطلبات|الشروط|المؤهلات",
    re.I,
)

# Arabic: "خبرة 5 سنوات", "3-5 سنوات خبرة", "خبرة لا تقل عن سنتين", "خمس سنوات".
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
_AR_WORDS = {"ثلاث": 3, "أربع": 4, "اربع": 4, "خمس": 5, "ست": 6, "سبع": 7, "ثماني": 8,
             "ثمان": 8, "تسع": 9, "عشر": 10}  # fmt: skip
_AR_YEARS = r"(?:سنوات|سنة|سنين|أعوام|اعوام|عام)"
_AR_MENTION = re.compile(
    rf"(?<![\d.])(?P<a>\d{{1,2}}|{'|'.join(_AR_WORDS)})\s*\+?\s*"
    rf"(?:(?:-|\u2013|إلى|الى)\s*(?P<b>\d{{1,2}})\s*)?{_AR_YEARS}"
    r"|(?P<two>سنتين|سنتان|عامين|عامان)"
)
_AR_EXPERIENCE = re.compile(r"خبر")
_AR_PREFERRED = re.compile(r"يفضل|يُفضل|يفضّل|يُفضّل|ميزة|أفضلية|افضلية")
_AR_CEILING_LEAD = re.compile(r"(?:لا تزيد عن|لا يزيد عن|أقل من|اقل من|بحد أقصى|حتى)\s*$")
_AR_NOT_ABOUT_YOU = re.compile(r"العمر|عمر المتقدم|تأسست|عقد لمدة")

_LIST_MARKER = re.compile(r"^\s*(?:[-*•·]|\d+[.)])\s+")
_SENTENCE_END = re.compile(
    r"(?<=[a-z0-9)]{2}[.!?])\s+(?=[A-Z(\"])|;\s+|\s+[•·]\s+|(?<=[؀-ۿ][.!؟])\s+"
)


@dataclass(frozen=True)
class _Mention:
    floor: float
    ceiling: float | None
    kind: _Section
    scope: Literal["overall", "skill", "degree", "sub"]
    alternative: bool = False

    @property
    def text(self) -> str:
        return f"{self.floor:g}-{self.ceiling:g}" if self.ceiling else f"{self.floor:g}+"


@dataclass(frozen=True)
class Years:
    """`label` is "" when the description states nothing; `floor` is set only for a required
    overall bar; `confident` is the only state that may drop a job."""

    label: str = ""
    kind: Kind = "required"
    floor: float | None = None
    confident: bool = False


def lines_of(text: str) -> list[tuple[str, bool]]:
    """(line, was a list item) for each non-empty line, spaces collapsed."""
    out = []
    for raw in re.sub(r"[^\S\r\n]+", " ", text.replace("\u2019", "'")).splitlines():
        rest = _LIST_MARKER.sub("", raw).strip()
        if rest:
            out.append((rest, bool(_LIST_MARKER.match(raw))))
    return out


def sentences(text: str) -> list[str]:
    """Sentences of a text, leaving abbreviations ("B.S.", "e.g.") whole."""
    return [s.strip() for line, _ in lines_of(text) for s in _SENTENCE_END.split(line) if s.strip()]


def _heading(line: str, item: bool) -> _Section | None:
    """The section a heading line opens, or None when the line is not a heading."""
    bare = re.sub(r"\s*\([^)]*\)\s*", " ", line).strip()
    colon = bare.endswith((":", "\uff1a"))
    if len(bare) > 60 or re.search(r"\d", bare) or (item and not colon):
        return None
    if _MENTION.search(bare) or _AR_MENTION.search(bare):
        return None  # "خبرة سنتين", "Five years of experience": a sentence, however short
    if not colon and (len(bare.split()) > 6 or bare.endswith((".", "!", "?"))):
        return None
    if _PREFERRED_HEADING.search(bare):
        return "preferred"
    if re.match(r"experience (?:in|with|of)\b", bare, re.I):
        return None  # "Experience in fintech:" introduces items, not a section
    return "required" if _REQUIRED_HEADING.search(bare) else "unclear"


def _kind(sentence: str, at: int, section: _Section) -> _Section:
    """Required or preferred from the nearest cue: the last before the mention, else the first
    after it, else the section's."""
    if _PREFERRED_END.search(sentence):
        return "preferred"
    cues: list[tuple[int, _Section]] = [
        (m.start(), "preferred") for m in _PREFERRED.finditer(sentence)
    ]
    cues += [(m.start(), "required") for m in _REQUIRED.finditer(sentence)]
    if not cues:
        # Under an unknown heading only a sentence addressed to the candidate is a bar.
        return "required" if section == "unclear" and _CANDIDATE_HAS.search(sentence) else section
    before = [c for c in cues if c[0] < at]
    return max(before)[1] if before else min(cues)[1]


def _number(raw: str) -> float:
    return float(_WORDS.get(raw.lower(), raw))


def _latin(sentence: str, section: _Section) -> list[_Mention]:
    if _NOT_ABOUT_YOU.search(sentence):
        return []
    if _COMPANY_VOICE.search(sentence) and not _CANDIDATE_VOICE.search(sentence):
        return []
    found: list[_Mention] = []
    for m in _MENTION.finditer(sentence):
        lead, trail = sentence[max(0, m.start() - 60) : m.start()], sentence[m.end() :]
        floor = _number(m["a"])
        ceiling = _number(m["b"]) if m["b"] else None
        if ceiling is not None and (m["join"] or "").lower() == "and" and not m["between"]:
            floor, ceiling = ceiling, None  # "3 and 5 years" is not a range
        if floor > 20 or _WINDOW_LEAD.search(lead) or _CEILING_LEAD.search(lead):
            continue
        if _OTHERS_LEAD.search(lead) or _CEILING_TRAIL.match(trail) or _TRAIL_NOT.match(trail):
            continue
        if not _TRAIL_OK.match(trail):
            continue
        if _TRAIL_BARE.match(trail) and not re.search(r"\bexp(?:erience)?\b", sentence, re.I):
            continue
        scope: Literal["overall", "skill", "degree", "sub"] = "overall"
        if (_DEGREE_OR_LEAD.search(lead) and not found) or _DEGREE_SUB_TRAIL.match(trail):
            scope = "degree"
        elif _SKILL_TRAIL.match(trail):
            scope = "skill"
        elif _SUB_LEAD.search(lead) and any(f.scope == "overall" for f in found):
            scope = "sub"
        found.append(
            _Mention(
                floor,
                ceiling if ceiling is not None and ceiling > floor else None,
                _kind(sentence, m.start(), section),
                scope,
            )
        )
    return found


def _arabic(sentence: str, section: _Section) -> list[_Mention]:
    if not _AR_EXPERIENCE.search(sentence) or _AR_NOT_ABOUT_YOU.search(sentence):
        return []
    kind: _Section = "preferred" if _AR_PREFERRED.search(sentence) else section
    found = []
    for m in _AR_MENTION.finditer(sentence):
        if _AR_CEILING_LEAD.search(sentence[: m.start()]):
            continue
        floor = 2.0 if m["two"] else float(_AR_WORDS.get(m["a"], m["a"]))
        ceiling = float(m["b"]) if m["b"] else None
        if floor <= 20:
            found.append(
                _Mention(floor, ceiling if ceiling and ceiling > floor else None, kind, "overall")
            )
    return found


def years_required(text: str) -> Years:
    """The stated years-of-experience requirement of a job description."""
    mentions: list[_Mention] = []
    section: _Section = "required"  # text before any heading reads as required
    previous: list[int] = []  # indexes of the bars of the last sentence that had any
    for line, item in lines_of(text.translate(_AR_DIGITS)):
        if heading := _heading(line, item):
            section = heading
            continue
        for sentence in _SENTENCE_END.split(line):
            found = _latin(sentence, section) + _arabic(sentence, section)
            here = list(range(len(mentions), len(mentions) + len(found)))
            mentions += found
            if _EQUIVALENT.search(sentence):  # its own bars, or the ones just before it
                for i in here or previous:
                    m = mentions[i]
                    mentions[i] = _Mention(m.floor, m.ceiling, m.kind, m.scope, True)
            previous = here or previous
    gating = [m for m in mentions if m.kind != "preferred" and m.scope == "overall"]
    if gating:
        low = min(gating, key=lambda m: m.floor)
        hard = not any(m.alternative for m in gating) and not any(
            m.kind == "unclear" and m.floor == low.floor for m in gating
        )
        return Years(low.text, "required", low.floor, hard)
    if _NO_EXPERIENCE.search(text):
        return Years("0+", "required", 0, True)
    if preferred := [m for m in mentions if m.kind == "preferred" and m.scope == "overall"]:
        return Years(min(preferred, key=lambda m: m.floor).text, "preferred")
    if skill := [m for m in mentions if m.kind == "required" and m.scope == "skill"]:
        return Years(min(skill, key=lambda m: m.floor).text, "skill")
    return Years()
