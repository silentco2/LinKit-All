"""Offline ghost-job scorer (English + Arabic). No AI, no network; only `ghost_histories` reads the DB.

A ghost job is a real company's posting that is stale, evergreen or never meant to be filled.
Vagueness rules adapted from ghost-job-detector by Bias V (MIT); patterns are re-written, and the
Arabic vocabulary is new. Repost and still-open signals come from `job_sightings` (core/sightings).

Scoring (weights are the named constants below):
- Time evidence: `stale_posting` (45 d +15, 90 d +25), `still_open` (>= 4 runs over >= 30 d +15,
  >= 60 d +25) and `reposted` (+20). stale + still_open share one budget of 30 points
  (`TIME_CAP`): stale counts first, still_open is trimmed to what is left, because both are the
  same fact seen twice (an old posting that is still listed).
- Text evidence: `vague_description` (the 0-30 vagueness sub-score scaled to at most 20),
  `evergreen_language` (+15), `vague_title` (+10), `no_salary` (+5). Their sum is capped at
  `TEXT_CAP` (45, trimming the last signals first) so wording alone never reaches the "likely"
  band (50): a ghost verdict needs age, sightings or reposts.
- Other: `hiring_surge` (+10).
Sum clamped to 0-100. Bands: < 35 low, < 50 medium, else high.
"""

# ruff: noqa: E501, RUF001  (regex tables, Arabic on purpose)

import re
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from linkit_all.core.models import Job
from linkit_all.core.sightings import company_run_counts, latest_run_id, sighting_stats
from linkit_all.matching.trust import Signal, Verdict
from linkit_all.matching.trust.normalize import fold_arabic, light
from linkit_all.matching.trust.scam import SalaryLike

# ---- weights and thresholds -------------------------------------------------------------------

STALE_DAYS = ((90.0, 25), (45.0, 15))
STILL_OPEN_MIN_RUNS = 4
STILL_OPEN_SPAN = ((60.0, 25), (30.0, 15))
TIME_CAP = 30  # stale_posting + still_open together
REPOST_URLS, REPOST_WEIGHT = 2, 20
EVERGREEN_WEIGHT = 15
VAGUE_TITLE_WEIGHT = 10
NO_SALARY_WEIGHT = 5
SURGE_MIN_OPEN, SURGE_FACTOR, SURGE_WEIGHT = 20, 3.0, 10
VAGUE_MAX = 20  # the 0-30 vagueness sub-score is scaled down to this
TEXT_CAP = 45  # below HIGH_FROM: wording alone cannot reach "high"
MEDIUM_FROM, HIGH_FROM = 35, 50
_MAX_CHARS = 30_000
_EVIDENCE_MAX = 80


@dataclass(frozen=True)
class GhostHistory:
    first_seen: datetime | None  # earliest sighting (core/sightings.py)
    seen_runs: int  # distinct discovery runs that saw it
    span_days: float  # last sighting - first sighting
    urls_seen: int  # distinct URLs among sightings (repost under a new URL/id)
    company_open_now: int  # jobs from this company seen in the latest run
    company_open_median: float  # median of that count over earlier runs (0 if no history)


NO_HISTORY = GhostHistory(None, 0, 0.0, 0, 0, 0.0)


# ---- vagueness (adapted rules) ----------------------------------------------------------------


def _ar(*phrases: str) -> str:
    """Alternation of Arabic phrases in the folded form `light()` produces."""
    return "|".join(re.escape(fold_arabic(p)).replace(r"\ ", r"\s+") for p in phrases)


_CUR = r"usd|gbp|eur|cad|aud|egp|sar|aed|qar|kwd|bhd|omr|" + _ar(
    "جنيه", "ريال", "درهم", "دينار", "دولار"
)
_NUM = r"\d[\d,]*(?:\.\d+)?"
_AMOUNT = re.compile(
    rf"(?:[$£€¥₹]\s?|\b(?:usd|gbp|eur|cad|aud|egp|sar|aed|qar|kwd)\s?){_NUM}(?:\s?k\b)?"
    rf"|\b{_NUM}\s?k\b"
    rf"|\b{_NUM}\s?(?:{_CUR})(?![\w])"
)
_PERIOD = re.compile(
    r"\s*(?:/|per)\s*(?:hr|hour|yr|year|annum|month|mo)\b|\s+(?:a|an)\s+(?:hour|year|month)\b"
    r"|\s+(?:hourly|monthly|annually|annual)\b|\s*(?:"
    + _ar("شهريا", "سنويا", "في الشهر", "بالساعه", "في الساعه", "كل شهر")
    + ")"
)
_JOIN = re.compile(r"\s*(?:[-–—]|to\b|" + _ar("الي", "إلى") + r")\s*")
_SCALE = re.compile(r"\s*(?:million|billion|[mb]\b|" + _ar("مليون", "مليار") + ")")
_RANGE_CUR = re.compile(rf"\b{_NUM}\s*(?:[-–—]|to\b)\s*{_NUM}\s?(?:{_CUR}|k\b)")


_DIGIT = re.compile(r"\d")


def has_pay(light_text: str) -> bool:
    """Pay in the text counts only as a range or an amount with a period ("$20/hr", "5000 egp
    monthly"); amounts followed by million/billion are not pay."""
    if _DIGIT.search(light_text) is None:
        return False
    if _RANGE_CUR.search(light_text):
        return True
    for m in _AMOUNT.finditer(light_text):
        end = m.end()
        tail = light_text[end : end + 40]
        if _SCALE.match(tail):
            continue
        if _PERIOD.match(tail):
            return True
        j = _JOIN.match(tail)
        if j:
            second = _AMOUNT.match(tail, j.end())
            if second and not _SCALE.match(
                light_text[end + second.end() : end + second.end() + 12]
            ):
                return True
    return False


class _Bi:
    """An English and an Arabic pattern; the Arabic one runs only on text that is not pure ASCII
    (much cheaper on the common case of an English posting)."""

    def __init__(self, en: str, ar: str, flags: int = 0) -> None:
        self._en = re.compile(en, flags)
        self._ar = re.compile(ar, flags)

    def search(self, text: str) -> re.Match[str] | None:
        m = self._en.search(text)
        if m is None and not text.isascii():
            m = self._ar.search(text)
        return m

    def findall(self, text: str) -> list[str]:
        out: list[str] = self._en.findall(text)
        if not text.isascii():
            out += self._ar.findall(text)
        return out


_YEARS = _Bi(
    r"\b\d+\s*\+?\s*(?:years?|yrs?)\b",
    r"\d+\s*\+?\s*(?:" + _ar("سنوات", "سنه", "سنين", "عاما", "عام") + r")(?![\w])"
    r"|(?:" + _ar("سنوات") + r")\s+(?:" + _ar("من") + r"\s+)?" + _ar("خبرة"),
)
_REPORTING = _Bi(
    r"\breports?\s+to\b|\bdirect reports?\b|\b(?:manage|manages|managing)\s+\d+\s+[a-z]",
    r"(?<!\w)(?:"
    + _ar("يتبع", "تحت إشراف", "يرفع تقاريره", "المدير المباشر", "يقدم تقاريره")
    + r")(?!\w)",
)
_QUANT = _Bi(
    r"\b(?:team|group|staff)\s+of\s+\d+\b|[$£€]\s?\d|\b\d[\d,]*\s*(?:%|percent|million|billion)"
    r"|\b\d[\d,]*\s*\+\s*(?!years?\b|yrs?\b)[a-z]|\b\d[\d,]*\s+(?!years?\b|days?\b|weeks?\b|months?\b|hours?\b)[a-z]{4,}s\b",
    r"(?:" + _ar("فريق من", "فريق مكون من", "فريق يضم") + r")\s*\d"
    r"|\b\d[\d,]*\s*(?:" + _ar("مليون", "مليار", "موظف", "عميل", "مشروع", "فرع", "منتج") + ")",
)
_ROLE_CONTEXT = _Bi(
    r"\b(?:using|with|including|via|through|certified|certification|proficient|experience|experienced|knowledge|responsible"
    r"|maintain\w*|build\w*|configur\w*|administer\w*|support\w*|implement\w*|manag\w*|develop\w*|design\w*|operat\w*"
    r"|analy\w+|reports?|reporting|triage|draft|process\w*|reconcile|documents?|systems?|platforms?|tools?|software|applications?)\b",
    r"(?<!\w)(?:"
    + _ar(
        "باستخدام",
        "خبرة",
        "معرفة",
        "مسؤول",
        "نظام",
        "انظمة",
        "أدوات",
        "برنامج",
        "برامج",
        "منصة",
        "تطبيق",
        "تطوير",
        "بناء",
        "تصميم",
        "تحليل",
    )
    + r")",
)
_ACRONYM = re.compile(r"\b[A-Z][A-Z0-9]{1,7}\b")
_ACRONYM_STOP = frozenset(
    {"AM", "PM", "US", "UK", "OR", "AN", "AS", "BE", "IS", "IT", "AT", "BY", "TO", "OF"}
    | {"IN", "ON", "WE", "DO", "IF", "SO", "NO", "OK", "ID", "A"}
)
_TRIM = re.compile(r"^[(\"'`“”]+|[)\"'`“”,.;:]+$")
_HEADING = frozenset(("who", "we", "are", "our", "about"))
_LINKERS = frozenset(("of", "and", "the", "for", "at", "&"))
_SENTENCES = re.compile(r"(?<=[.!?؟\n])\s+")
_ACTION = re.compile(
    r"\b(?:draft\w*|build\w*|built|triage\w*|configur\w*|administer\w*|implement\w*|develop\w*|design\w*|analy[sz]\w*"
    r"|reconcil\w*|audit\w*|document\w*|maintain\w*|deploy\w*|migrat\w*|writ\w+|wrote|review\w*|resolv\w*|diagnos\w*"
    r"|install\w*|operat\w*|schedul\w*|prepar\w*|counsel\w*|assess\w*|treat\w*|cod(?:e|es|ed|ing))\b",
    re.I,
)
_AR_ACTION = re.compile(
    r"(?<!\w)(?:"
    + _ar(
        "تطوير",
        "بناء",
        "تصميم",
        "اعداد",
        "إعداد",
        "تحليل",
        "تنفيذ",
        "مراجعة",
        "صيانة",
        "تركيب",
        "تشغيل",
        "ادارة",
        "إدارة",
    )
    + r")"
)
_VAGUE_COLLOCATION = re.compile(
    r"\b(?:support|drive|leverage|champion|spearhead)\s+(?:[\w-]+\s+){0,3}(?:initiatives?|results?|outcomes?|synergies|excellence|innovation|success|change)\b"
    r"|\bwear many hats\b|\bother duties as assigned\b|\bfast-paced environment\b",
    re.I,
)
_OBJECT = re.compile(r"\b(?:[A-Z][A-Za-z0-9.+/-]{2,}|\d|Tier\s+\d|[a-z]+-[a-z]+)\b")
_LATIN_OR_DIGIT = re.compile(r"[A-Za-z]{2,}|\d")
_BUZZ = _Bi(
    r"\b(?:rockstars?|ninjas?|whizz?(?:es)?|gurus?|mavericks?|synerg(?:y|ies)|disrupt\w*|innovat(?:e|es|ed|ing)|growth mindset"
    r"|wear many hats|fast-paced environment|dynamic environment|self-starters?|go-getters?|other duties as assigned)\b",
    r"(?<!\w)(?:"
    + _ar(
        "روك ستار",
        "نينجا",
        "عبقري",
        "شغوف",
        "شغوفين",
        "بيئة عمل ديناميكية",
        "بيئة ديناميكية",
        "سريعة الوتيرة",
        "سريعة الايقاع",
        "اي مهام اخرى",
        "أي مهام أخرى",
        "مهام اخرى حسب الحاجة",
        "تعدد المهام",
        "صاحب مبادرة",
    )
    + r")",
)


def _named_tool(text: str) -> bool:
    for sentence in _SENTENCES.split(text):
        if not sentence or not _ROLE_CONTEXT.search(
            sentence if sentence.isascii() else light(sentence)
        ):
            continue
        if any(m.group(0) not in _ACRONYM_STOP for m in _ACRONYM.finditer(sentence)):
            return True
        for i, raw in enumerate(sentence.split()):
            tok = _TRIM.sub("", raw)
            if (
                tok[:1].isupper()
                and tok.lower() not in _HEADING
                and tok.lower() not in _LINKERS
                and tok[0].isascii()
                and (i > 0 or (len(tok) > 1 and any(c.isupper() for c in tok[1:])))
            ):
                return True
    return False


def _deliverable(text: str, folded: str) -> bool:
    for m in _ACTION.finditer(text):
        window = text[m.start() : m.start() + 80]
        if not _VAGUE_COLLOCATION.search(window) and _OBJECT.search(window[len(m.group(0)) :]):
            return True
    if not folded.isascii():
        for m in _AR_ACTION.finditer(folded):
            if _LATIN_OR_DIGIT.search(folded[m.end() : m.end() + 60]):
                return True
    return False


def _specificity_flags(text: str, folded: str) -> int:
    """How many of five concrete-content flags are present (stops counting at 3)."""
    checks: tuple[Callable[[], bool], ...] = (
        lambda: _YEARS.search(folded) is not None,
        lambda: _REPORTING.search(folded) is not None,
        lambda: _QUANT.search(folded) is not None,
        lambda: _named_tool(text),
        lambda: _deliverable(text, folded),
    )
    n = 0
    for check in checks:
        if check():
            n += 1
            if n >= 3:
                break
    return n


def _in_title(phrase: str, title: str) -> bool:
    if not title:
        return False
    if phrase in title:
        return True
    return phrase.endswith("s") and phrase[:-1] in title


def vagueness(
    description: str,
    title: str,
    has_structured_pay: bool,
    *,
    folded: str | None = None,
    text_pay: bool | None = None,
) -> tuple[int, str]:
    """0-30 vagueness sub-score and a short reason. An empty description is "not loaded": (0, "")."""
    text = description.strip()[:_MAX_CHARS]
    if not text:
        return 0, ""
    if len(text) < 50:
        return 30, f"only {len(text)} characters"
    folded = light(text) if folded is None else folded
    words = len(text.split())
    parts: list[str] = []
    score = 0
    if words < 150:
        score += 30
        parts.append(f"{words} words")
    elif words < 250:
        score += 15
        parts.append(f"{words} words")
    if text_pay is None:
        text_pay = has_pay(folded)
    if not has_structured_pay and not text_pay:
        score += 10
        parts.append("no pay")
    if text.count("?") + text.count("؟") > 5:
        score += 15
        parts.append("many questions")
    title_folded = light(title)
    hits = [h for h in _BUZZ.findall(folded) if not _in_title(h, title_folded)]
    density = len(hits) / words * 100
    if density >= 2:
        score += 20
        parts.append(f"{len(hits)} buzzwords")
    elif density >= 1:
        score += 10
        parts.append(f"{len(hits)} buzzwords")
    flags = _specificity_flags(text, folded)
    penalty = 0 if flags >= 3 else (8, 16, 25)[2 - flags]
    if penalty:
        score += penalty
        parts.append(f"{flags} specifics")
    return min(score, 30), ", ".join(parts)


# ---- evergreen language and vague titles ------------------------------------------------------

_EVERGREEN = _Bi(
    r"\balways\s+(?:looking|hiring|recruiting|accepting)\b|\bwe\s+are\s+always\s+hiring\b"
    r"|\btalent\s+(?:pool|community|network)\b|\bfuture\s+(?:opportunit\w+|openings?|vacanc\w+|roles?)\b"
    r"|\bgeneral\s+application\b|\bexpressions?\s+of\s+interest\b"
    r"|\b(?:talent|candidate)\s+pipeline\b|\bpipeline\s+of\s+(?:candidates|talent)\b|\b(?:build\w*|join\w*)\s+(?:a|our|the)\s+(?:\w+\s+)?pipeline\b",
    r"(?<!\w)(?:"
    + _ar(
        "نبحث دائما",
        "نبحث باستمرار",
        "دائما نبحث",
        "نوظف دائما",
        "التوظيف مفتوح دائما",
        "بنك المواهب",
        "مجتمع المواهب",
        "قاعدة بيانات المواهب",
        "فرص مستقبلية",
        "وظائف مستقبلية",
        "طلب عام",
        "التقديم العام",
        "اظهار الاهتمام",
        "إبداء الاهتمام",
    )
    + r")",
)
_VAGUE_TITLE = _Bi(
    r"\b(?:various|multiple|several|many)\s+(?:positions?|roles?|openings?|vacanc\w+|jobs?)\b"
    r"|\bopen\s+application\b|\bgeneral\s+application\b|\btalent\s+(?:pool|community|network)\b|\bfuture\s+opportunit\w+\b",
    r"(?<!\w)(?:"
    + _ar(
        "وظائف متعددة",
        "وظائف متنوعة",
        "عدة وظائف",
        "شواغر متعددة",
        "عدة شواغر",
        "طلب عام",
        "بنك المواهب",
        "فرص مستقبلية",
    )
    + r")",
)


def _snip(text: str, start: int, end: int) -> str:
    return " ".join(text[max(0, start - 10) : end + 10].split())[:_EVIDENCE_MAX]


# ---- scoring ----------------------------------------------------------------------------------


def _naive_utc(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def _has_salary(salary: SalaryLike | Mapping[str, object] | None) -> bool:
    if not salary:
        return False
    for key in ("min", "max", "salary_min", "salary_max"):
        v = salary.get(key)
        if isinstance(v, int | float) and v > 0:
            return True
    return False


def _tier(value: float, table: Sequence[tuple[float, int]]) -> int:
    return next((w for limit, w in table if value >= limit), 0)


def score_ghost(
    title: str,
    company: str,
    description: str,
    posted_at: datetime | None,
    salary: SalaryLike | None,
    history: GhostHistory,
    now: datetime,
) -> Verdict:
    """Score one posting 0-100 for ghost-job likelihood, with the signals that explain it."""
    now = _naive_utc(now)
    signals: list[Signal] = []

    # time evidence: age from the earliest trustworthy date, then sightings
    dates = [_naive_utc(d) for d in (posted_at, history.first_seen) if d is not None]
    dates = [d for d in dates if d <= now]
    budget = TIME_CAP
    if dates:
        age = (now - min(dates)).total_seconds() / 86400
        if w := _tier(age, STALE_DAYS):
            w = min(w, budget)
            budget -= w
            signals.append(Signal("stale_posting", w, f"{age:.0f} days old"))
    if history.seen_runs >= STILL_OPEN_MIN_RUNS and (
        w := _tier(history.span_days, STILL_OPEN_SPAN)
    ):
        w = min(w, budget)
        if w > 0:
            signals.append(
                Signal(
                    "still_open",
                    w,
                    f"seen in {history.seen_runs} runs over {history.span_days:.0f} days",
                )
            )
    if history.urls_seen >= REPOST_URLS:
        signals.append(Signal("reposted", REPOST_WEIGHT, f"listed under {history.urls_seen} URLs"))

    # text evidence, capped as a group
    text_sigs: list[Signal] = []
    pay = _has_salary(salary)
    text = description.strip()[:_MAX_CHARS]
    desc = light(text) if text else ""
    text_pay = pay or (bool(text) and has_pay(desc))
    sub, why = vagueness(text, title, pay, folded=desc, text_pay=text_pay)
    if w := round(sub * VAGUE_MAX / 30):
        text_sigs.append(Signal("vague_description", w, why[:_EVIDENCE_MAX]))
    if m := _EVERGREEN.search(desc):
        text_sigs.append(
            Signal("evergreen_language", EVERGREEN_WEIGHT, _snip(desc, m.start(), m.end()))
        )
    t = light(title)
    if m := _VAGUE_TITLE.search(t):
        text_sigs.append(Signal("vague_title", VAGUE_TITLE_WEIGHT, _snip(t, m.start(), m.end())))
    if text and not text_pay:
        text_sigs.append(Signal("no_salary", NO_SALARY_WEIGHT, "no pay stated"))
    room = TEXT_CAP
    for s in text_sigs:
        w = min(s.weight, room)
        room -= w
        if w > 0:
            signals.append(Signal(s.code, w, s.evidence))

    if (
        history.company_open_now >= SURGE_MIN_OPEN
        and history.company_open_median > 0
        and history.company_open_now >= SURGE_FACTOR * history.company_open_median
    ):
        signals.append(
            Signal(
                "hiring_surge",
                SURGE_WEIGHT,
                f"{history.company_open_now} open vs median {history.company_open_median:g}",
            )
        )

    score = max(0, min(100, sum(s.weight for s in signals)))
    band = "low" if score < MEDIUM_FROM else "medium" if score < HIGH_FROM else "high"
    return Verdict(score, tuple(signals), band)


# ---- history from the database ----------------------------------------------------------------


def ghost_histories(session: Session, jobs: Sequence[Job]) -> dict[int, GhostHistory]:
    """History for every job, in 1 + ceil(n/500) + ceil(companies/500) queries."""
    if not jobs:
        return {}
    stats = sighting_stats(session, [j.id for j in jobs])
    latest = latest_run_id(session)
    counts = company_run_counts(session, {j.company for j in jobs}) if latest is not None else {}
    medians: dict[str, tuple[int, float]] = {}
    for company, per_run in counts.items():
        earlier = [n for run, n in per_run.items() if run != latest]
        medians[company] = (
            per_run.get(latest, 0) if latest is not None else 0,
            float(statistics.median(earlier)) if earlier else 0.0,
        )
    out: dict[int, GhostHistory] = {}
    for job in jobs:
        now_n, med = medians.get(job.company, (0, 0.0))
        st = stats.get(job.id)
        out[job.id] = GhostHistory(
            st.first if st else None,
            st.runs if st else 0,
            (st.last - st.first).total_seconds() / 86400 if st else 0.0,
            st.urls if st else 0,
            now_n,
            med,
        )
    return out
