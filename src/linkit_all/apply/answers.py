"""Answer application questions without guessing.

Order per question: standard profile fields -> sensitive rules (profile only, never the AI)
-> answer bank -> AI draft from the CV (non-sensitive only) -> Action Center if required.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel
from rapidfuzz import fuzz

Kind = Literal[
    "text", "textarea", "email", "tel", "number", "url", "date",
    "select", "radio", "combobox", "yesno", "checkbox", "multi", "file",
]  # fmt: skip
CHOICE_KINDS = {"select", "radio", "combobox", "yesno"}


@dataclass
class Question:
    key: str  # this form's handle for the field (data-lk attribute or ATS field name)
    label: str
    kind: Kind
    required: bool = False
    options: list[str] = field(default_factory=list)
    name: str = ""  # html name/id, used to spot standard fields
    description: str = ""


class ApplicationAnswers(BaseModel):
    """Answers the user gives once in the setup wizard. Sensitive ones are used only from here."""

    first_name: str = ""
    last_name: str = ""
    city: str = ""
    country: str = ""
    current_company: str = ""
    current_title: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    years_experience: int | None = None
    notice_period: str = ""  # e.g. "1 month"
    heard_about: str = ""  # default for "How did you hear about us?"
    willing_to_relocate: bool | None = None
    # Sensitive (CLAUDE.md §2): never guessed. None/empty means "ask me in the Action Center".
    authorized_countries: list[str] = []
    needs_sponsorship: bool | None = None
    salary_expectation: str = ""  # as you would type it, e.g. "30000"
    salary_currency: str = ""
    eeo_gender: str | None = None  # male | female | non_binary | decline
    eeo_race: str | None = (
        None  # asian | black | hispanic | white | middle_eastern | native | pacific | two_or_more | decline
    )
    eeo_hispanic: str | None = None  # yes | no | decline
    eeo_veteran: str | None = None  # not_veteran | veteran | decline
    eeo_disability: str | None = None  # no | yes | decline
    acknowledge_privacy: bool | None = None  # privacy notices, data-processing consent
    acknowledge_legal: bool | None = None  # arbitration agreements, "I certify this is true"


@dataclass
class Context:
    full_name: str
    email: str
    phone: str
    location: str
    answers: ApplicationAnswers
    job_location: str = ""
    job_source: str = ""  # where we found the job, for "how did you hear about us"
    resume_path: str = ""
    cover_letter_path: str = ""  # filled in when the form has a cover-letter field


@dataclass
class Missing:
    question: Question
    reason: str
    sensitive: bool = False


# --- sensitive questions -----------------------------------------------------------

# Checked in order: "require sponsorship ... authorization to work" is about sponsorship.
_SENSITIVE: list[tuple[str, re.Pattern[str]]] = [
    (cat, re.compile(rx, re.I))
    for cat, rx in [
        ("sponsorship", r"sponsor|\bvisa\b"),
        ("work_authorization", r"authori[sz]ed to work|work authori[sz]ation|right to work|eligib\w+ to work|"
                               r"legally (able|permitted|allowed|entitled) to work|work permit"),
        ("salary", r"salary|compensation|pay expectation|expected pay|desired pay|rate expectation|\bctc\b"),
        ("criminal", r"criminal|convicted|conviction|felony|misdemeano"),
        ("eeo_race", r"\brace\b|ethnicit"),
        ("eeo_hispanic", r"hispanic|latin[oax]"),
        ("eeo_gender", r"\bgender\b|\bsex\b"),
        ("eeo_veteran", r"veteran|military service|armed forces"),
        ("eeo_disability", r"disabilit"),
        ("eeo_other", r"sexual orientation|transgender|\bpronouns?\b|lgbt|religio|marital|date of birth|\bage\b|how old"),
        # Being recorded or transcribed (AI notetakers) is its own decision, never a default.
        ("recording_consent", r"notetaker|\brecord(ing|ed)?\b.*\b(interview|call|conversation)|transcri"),
        ("acknowledge_legal", r"arbitration|\bcertify\b|attest|true and (complete|correct|accurate)|"
                              r"non-?compete|non-?solicit|legally binding"),
        ("acknowledge_privacy", r"privacy (notice|policy|statement)|data (privacy|protection|processing)|gdpr|"
                                r"\bconsent\b|\backnowledge"),
    ]
]  # fmt: skip


def sensitive_category(q: Question) -> str | None:
    """The question text decides; the description (often a generic EEO paragraph) only if
    the question alone says nothing."""
    text = q.label
    if q.kind in ("multi", "checkbox"):  # "Please review:" [x] "I acknowledge the privacy notice"
        text += " " + " ".join(q.options)
    for source in (text, q.description):
        if found := next((cat for cat, rx in _SENSITIVE if rx.search(source)), None):
            return found
    return None


_COUNTRIES = {
    "united states": ["united states", "u.s.", "usa", "america", "san francisco", "new york", "seattle",
                      "boston", "austin", "chicago", "los angeles"],
    "united kingdom": ["united kingdom", "u.k.", "britain", "england", "london", "scotland"],
    "canada": ["canada", "toronto", "vancouver", "montreal"],
    "egypt": ["egypt", "cairo", "giza", "alexandria", "6th of october", "new capital"],
    "united arab emirates": ["united arab emirates", "uae", "emirates", "dubai", "abu dhabi", "sharjah"],
    "saudi arabia": ["saudi arabia", "saudi", "ksa", "riyadh", "jeddah", "dammam"],
    "qatar": ["qatar", "doha"], "kuwait": ["kuwait"], "bahrain": ["bahrain", "manama"],
    "oman": ["oman", "muscat"], "jordan": ["jordan", "amman"], "morocco": ["morocco", "casablanca"],
    "ireland": ["ireland", "dublin"], "germany": ["germany", "berlin", "munich"],
    "netherlands": ["netherlands", "amsterdam"], "france": ["france", "paris"], "spain": ["spain", "madrid"],
    "india": ["india", "bangalore", "bengaluru", "hyderabad", "mumbai"], "singapore": ["singapore"],
    "australia": ["australia", "sydney", "melbourne"], "japan": ["japan", "tokyo"],
}  # fmt: skip
_ISO = {"us": "united states", "gb": "united kingdom", "uk": "united kingdom", "eg": "egypt",
        "ae": "united arab emirates", "sa": "saudi arabia", "ca": "canada", "ie": "ireland",
        "de": "germany", "in": "india", "qa": "qatar", "kw": "kuwait"}  # fmt: skip
_THIS_COUNTRY = re.compile(r"country where (the|this) (job|role|position)|this (country|location)|"
                           r"where the (job|role|position) is|country (for|to) which you (are )?apply", re.I)  # fmt: skip


def country_of(text: str) -> str | None:
    if re.search(r"\bU\.?S\.?A?\b", text):  # case-sensitive: "contact us" is not the USA
        return "united states"
    low = text.lower()
    for country, aliases in _COUNTRIES.items():
        if any(re.search(rf"(?<![a-z]){re.escape(a)}(?![a-z])", low) for a in aliases):
            return country
    tail = low.rsplit(",", 1)[-1].strip()
    return _ISO.get(tail)


def canonical_country(name: str) -> str:
    return country_of(name) or name.strip().lower()


# --- picking options -------------------------------------------------------------

_DECLINE = re.compile(r"decline|prefer not|do not wish|don.?t wish|not to (disclose|answer|say|self)|"
                      r"choose not|rather not", re.I)  # fmt: skip
_CANON: dict[str, re.Pattern[str]] = {
    "decline": _DECLINE,
    "male": re.compile(r"^(male|man)\b", re.I),
    "female": re.compile(r"^(female|woman)\b", re.I),
    "non_binary": re.compile(r"non.?binary", re.I),
    "not_veteran": re.compile(r"not a (protected )?veteran|^no\b", re.I),
    "veteran": re.compile(r"identify as .*veteran|^(yes|i am a (protected )?veteran)", re.I),
    "yes": re.compile(r"^yes\b", re.I),
    "no": re.compile(r"^no\b", re.I),
    "asian": re.compile(r"^asian", re.I),
    "black": re.compile(r"black|african", re.I),
    "hispanic": re.compile(r"^hispanic|^latin", re.I),
    "white": re.compile(r"^white", re.I),
    "middle_eastern": re.compile(r"middle eastern|north african|\bmena\b|arab", re.I),
    "native": re.compile(r"american indian|alaska|indigenous|first nations", re.I),
    "pacific": re.compile(r"pacific islander|hawaiian", re.I),
    "two_or_more": re.compile(r"two or more|multiracial|mixed", re.I),
}


def pick_canonical(options: list[str], value: str) -> str | None:
    """The option that means `value` (e.g. "decline" -> "Decline to self-identify")."""
    pattern = _CANON.get(value)
    if pattern is None:
        return None
    if value != "decline":  # "No, I decline..." must not count as a plain "no"
        options = [o for o in options if not _DECLINE.search(o)]
    return next((o for o in options if pattern.search(o.strip())), None)


def pick_option(options: list[str], value: str) -> str | None:
    """Best option for a free-text value: exact, prefix, then close fuzzy match."""
    v = value.strip().lower()
    if not v:
        return None
    for o in options:
        if o.strip().lower() == v:
            return o
    for o in options:
        if o.strip().lower().startswith(v) or v.startswith(o.strip().lower()):
            return o
    scored = [(fuzz.WRatio(v, o.lower()), o) for o in options]
    best = max(scored, default=(0.0, ""))
    return best[1] if best[0] >= 88 else None


def yes_no(q: Question, yes: bool) -> Any:
    if q.kind == "checkbox":
        return yes
    if q.kind in CHOICE_KINDS:
        return pick_canonical(q.options or ["Yes", "No"], "yes" if yes else "no")
    return "Yes" if yes else "No"


# --- standard and sensitive answers -------------------------------------------------------

_STANDARD: list[tuple[str, re.Pattern[str]]] = [
    (key, re.compile(rx, re.I))
    for key, rx in [
        ("first_name", r"first[ _-]?name|given name|forename"),
        ("last_name", r"last[ _-]?name|surname|family name"),
        ("email", r"e-?mail"),
        ("phone", r"phone|mobile"),
        ("linkedin", r"linkedin"),
        ("github", r"github"),
        ("portfolio", r"portfolio|personal (web)?site|^website$|urls\[other\]"),
        ("current_company", r"current (company|employer)|^org$"),
        ("current_title", r"current (job )?(title|role|position)"),
        ("full_name", r"^(full |your |legal )?name$|_systemfield_name"),
        ("country", r"^country\b"),
        ("city", r"^(city|location|current location|location \(city\))\b"),
        ("heard_about", r"how did you (hear|find|learn)|where did you (hear|find|see)|referral source"),
        ("notice_period", r"notice period"),
        ("years_experience", r"years of (professional |relevant |work )?experience|how many years"),
        ("relocate", r"relocat"),
    ]
]  # fmt: skip
_SOURCE_NAMES = {"linkedin": "LinkedIn", "indeed": "Indeed", "glassdoor": "Glassdoor", "google": "Google",
                 "zip_recruiter": "ZipRecruiter", "bayt": "Bayt", "wuzzuf": "Wuzzuf"}  # fmt: skip


def _standard_value(key: str, ctx: Context) -> Any:
    a = ctx.answers
    first, _, last = ctx.full_name.strip().partition(" ")
    values: dict[str, Any] = {
        "first_name": a.first_name or first,
        "last_name": a.last_name or last,
        "full_name": ctx.full_name,
        "email": ctx.email,
        "phone": ctx.phone,
        "linkedin": a.linkedin,
        "github": a.github,
        "portfolio": a.portfolio,
        "current_company": a.current_company,
        "current_title": a.current_title,
        "country": a.country or (country_of(ctx.location) or "").title(),
        "city": a.city or ctx.location,
        "heard_about": a.heard_about or _SOURCE_NAMES.get(ctx.job_source, "Company website"),
        "notice_period": a.notice_period,
        "years_experience": "" if a.years_experience is None else str(a.years_experience),
        "relocate": a.willing_to_relocate,
    }
    return values.get(key)


def standard_answer(q: Question, ctx: Context) -> Any:
    """Answer from the profile, or None when this is not a standard field."""
    for key, rx in _STANDARD:
        if not (rx.search(q.name) or rx.search(q.label)):
            continue
        value = _standard_value(key, ctx)
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            return yes_no(q, value)
        if q.kind == "combobox" and not q.options:
            return value  # searchable list (country, city): typed, then the first match is picked
        if q.kind in CHOICE_KINDS or q.kind == "multi":
            if key == "years_experience":
                return _pick_range(q.options, int(value))
            picked = pick_option(q.options, value)
            return [picked] if picked and q.kind == "multi" else picked
        return value
    return None


def _pick_range(options: list[str], years: int) -> str | None:
    """'5-7' / '7+' / '0-1' style options containing `years`."""
    for o in options:
        nums = [int(n) for n in re.findall(r"\d+", o)]
        if len(nums) >= 2 and nums[0] <= years <= nums[1]:
            return o
        if len(nums) == 1 and "+" in o and years >= nums[0]:
            return o
        if len(nums) == 1 and o.strip() == str(years):
            return o
    return None


def sensitive_answer(q: Question, category: str, ctx: Context) -> tuple[Any, str]:
    """(value, "") or (None, why the user must answer)."""
    a = ctx.answers
    if category.startswith("eeo_"):
        value = getattr(a, category, None)
        if not value:
            return None, "demographic question you have not answered in setup"
        if q.kind in CHOICE_KINDS or q.kind == "multi":
            picked = pick_canonical(q.options, value)
            if picked is None:
                return None, f"no option matches your saved answer ({value})"
            return ([picked] if q.kind == "multi" else picked), ""
        return value.replace("_", " ").capitalize(), ""
    if category in ("work_authorization", "sponsorship"):
        text = f"{q.label} {q.description}"
        country = (
            country_of(ctx.job_location) if _THIS_COUNTRY.search(text) else None
        ) or country_of(text)
        authorized = {canonical_country(c) for c in a.authorized_countries}
        if category == "work_authorization":
            if country is None or not authorized:
                return None, "work authorization: country unknown or not set in your profile"
            return yes_no(q, country in authorized), ""
        if country is not None and country in authorized:
            return yes_no(q, False), ""  # authorized there already: no sponsorship needed
        if a.needs_sponsorship is None:
            return None, "visa sponsorship: not set in your profile"
        return yes_no(q, a.needs_sponsorship), ""
    if category == "salary":
        if not a.salary_expectation or q.kind in CHOICE_KINDS:
            return None, "salary expectation needed"
        number = re.sub(r"[^\d.]", "", a.salary_expectation)
        if q.kind == "number":
            return number, ""
        return f"{a.salary_expectation} {a.salary_currency}".strip(), ""
    if category in ("acknowledge_privacy", "acknowledge_legal"):
        agreed = getattr(a, category)
        if agreed is not True:
            return None, "acknowledgement you have not pre-approved in setup"
        if q.kind == "multi":
            return list(q.options), ""
        return (True if q.kind == "checkbox" else _agree_option(q)), ""
    return None, f"{category.replace('_', ' ')} question: only you can answer"


def _agree_option(q: Question) -> Any:
    agree = re.compile(r"^(yes|i (acknowledge|agree|consent|confirm|accept|have read))", re.I)
    return next((o for o in q.options if agree.search(o)), None) if q.options else "Yes"


def file_answer(q: Question, ctx: Context) -> str | None:
    text = f"{q.name} {q.label}".lower()
    if re.search(r"cover", text):
        return ctx.cover_letter_path or None
    if re.search(r"resume|\bcv\b|curriculum", text):
        return ctx.resume_path or None
    return None


def is_cover_letter(q: Question) -> bool:
    return bool(re.search(r"cover.?letter", f"{q.name} {q.label}", re.I))


@dataclass
class Resolution:
    answers: dict[str, Any] = field(default_factory=dict)  # key -> value
    sources: dict[str, str] = field(default_factory=dict)  # key -> profile|sensitive|bank|ai|file
    pending: list[Question] = field(default_factory=list)  # for the bank / AI
    missing: list[Missing] = field(default_factory=list)  # for the user


def resolve_static(questions: list[Question], ctx: Context) -> Resolution:
    """Everything answerable without the bank or the AI. Sensitive misses go to `missing`."""
    r = Resolution()
    for q in questions:
        if q.kind == "file":
            if (path := file_answer(q, ctx)) is not None:
                r.answers[q.key], r.sources[q.key] = path, "file"
            elif q.required:
                r.missing.append(Missing(q, "file the app cannot provide"))
            continue
        if (category := sensitive_category(q)) is not None:
            if category.startswith("acknowledge") and not q.required:
                continue  # optional consents (marketing emails, ...) stay unticked
            value, why = sensitive_answer(q, category, ctx)
            if value is not None:
                r.answers[q.key], r.sources[q.key] = value, "sensitive"
            elif q.required:
                r.missing.append(Missing(q, why, sensitive=True))
            continue
        value = standard_answer(q, ctx)
        if value is not None:
            r.answers[q.key], r.sources[q.key] = value, "profile"
        else:
            r.pending.append(q)  # answer bank, then the AI (cover letters included)
    return r


def valid_for(q: Question, value: Any) -> bool:
    """An AI or bank answer must fit the field (a real option, a bool for checkboxes)."""
    if value is None or value == "" or value == []:
        return False
    if q.kind in CHOICE_KINDS:
        return isinstance(value, str) and value in q.options
    if q.kind == "multi":
        return isinstance(value, list) and all(v in q.options for v in value)
    if q.kind == "checkbox":
        return isinstance(value, bool)
    return isinstance(value, str)
