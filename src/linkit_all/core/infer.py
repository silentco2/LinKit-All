# ruff: noqa: RUF001
"""Rule-based CV reading: facts from the CV text, then setup suggestions from those facts.

No AI and no invention (CLAUDE.md §2): every value comes from the CV text or links, or from a
fixed rule over them. Sensitive answers are never derived; the only one touched is the
authorized-countries *suggestion*, which stays at level "suggest" until the user taps it.
Nothing here logs CV text.
"""

import re
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any, Literal

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from pydantic import BaseModel

from linkit_all.apply.answers import country_of

Source = Literal["cv", "country", "roles", "years", "default", "ai"]
Level = Literal["auto", "suggest", "ask"]


class InferredValue(BaseModel):
    value: Any
    source: Source
    level: Level
    check: bool = False  # True = the rule is unsure; the UI asks the user to look


class Experience(BaseModel):
    title: str = ""
    company: str = ""
    start: date | None = None
    end: date | None = None
    current: bool = False
    intern: bool = False


class CvFacts(BaseModel):
    full_name: str = ""
    name_check: bool = False  # several name-like lines near the top
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    experiences: list[Experience] = []
    education: list[str] = []  # degree / institution parts, dates removed
    skills: list[str] = []


# --- small text helpers --------------------------------------------------------------

# Arabic-Indic and Persian digits -> ASCII, so dates and phones parse the same way.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_INVISIBLE = re.compile("[\u200b\u200e\u200f\u202a-\u202e]")
_JUNK = " \t|•·,،;؛:–—-()[]*▪●◦"
_BULLETS = "•-*▪◦●–—·"

# Arabic country/city names (country_of knows English only); whole-word match.
_AR_COUNTRIES = {
    "مصر": "egypt", "القاهرة": "egypt", "الجيزة": "egypt", "الإسكندرية": "egypt",
    "السعودية": "saudi arabia", "الرياض": "saudi arabia", "جدة": "saudi arabia",
    "الإمارات": "united arab emirates", "دبي": "united arab emirates",
    "أبوظبي": "united arab emirates", "قطر": "qatar", "الدوحة": "qatar", "الكويت": "kuwait",
    "البحرين": "bahrain", "سلطنة عمان": "oman", "الأردن": "jordan", "المغرب": "morocco",
}  # fmt: skip
_AR_COUNTRY_RX = re.compile("(?<!\\w)(" + "|".join(map(re.escape, _AR_COUNTRIES)) + ")(?!\\w)")


def _country(text: str) -> str | None:
    """English lower-case country name for a place string (EN or AR), else None."""
    if m := _AR_COUNTRY_RX.search(text):
        return _AR_COUNTRIES[m.group(1)]
    return country_of(text)


def _dedupe(items: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it.casefold() not in seen:
            seen.add(it.casefold())
            out.append(it)
    return out


def _lines(texts: Sequence[str]) -> list[str]:
    out: list[str] = []
    for t in texts:
        for ln in t.translate(_DIGITS).splitlines():
            ln = re.sub(r"[ \t\u00a0]+", " ", _INVISIBLE.sub("", ln)).strip()
            if ln:
                out.append(ln)
    return out


# --- section headings ------------------------------------------------------------------

_HEADS = {
    "experience": "experience|work experience|professional experience|employment|employment history"
    "|work history|career history|experiences|الخبرات|الخبرة|الخبرة العملية|الخبرات العملية"
    "|الخبرات المهنية|الخبرة المهنية|خبرات",
    "education": "education|academic background|qualifications|education and qualifications"
    "|التعليم|المؤهلات|المؤهلات العلمية|التعليم والمؤهلات|المؤهل العلمي",
    "skills": "skills|technical skills|key skills|core skills|skills and tools|skills & tools"
    "|المهارات|المهارات التقنية|المهارات الفنية|المهارات الشخصية",
    "other": "summary|profile|objective|professional summary|projects|certifications|certificates"
    "|courses|languages|references|awards|interests|volunteering|publications|ملخص|نبذة"
    "|نبذة عني|المشاريع|الشهادات|الدورات|اللغات|الجوائز|الاهتمامات|التطوع|المراجع",
}
_HEAD = {name: sec for sec, names in _HEADS.items() for name in names.split("|")}


def _heading(line: str) -> str | None:
    if len(line) > 40 or line.count(" ") > 4:
        return None
    return _HEAD.get(re.sub(r"^[\W_]+|[\W_]+$", "", line.lower()))


# --- titles, dates -------------------------------------------------------------------

_TITLE_RX = re.compile(
    r"\b(engineer|developer|programmer|manager|analyst|accountant|designer|specialist|consultant"
    r"|officer|director|lead|head|intern|assistant|coordinator|administrator|architect|executive"
    r"|representative|supervisor|technician|scientist|trainee|teacher|nurse|sales|marketing"
    r"|tester|auditor|clerk|secretary|recruiter|translator|writer|editor|owner|founder)\b"
    r"|مهندس|مطور|مدير|محاسب|محلل|مصمم|أخصائي|اخصائي|مسؤول|مشرف|منسق|متدرب|مبرمج|مندوب|مسوق",
    re.I,
)
_INTERN_RX = re.compile(r"intern|trainee|internship|متدرب|تدريب", re.I)

_AR_MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "إبريل": 4, "مايو": 5,
    "يونيو": 6, "يونية": 6, "يوليو": 7, "يوليه": 7, "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9,
    "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
}  # fmt: skip
_EN_ABBR = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
_MON = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|" + "|".join(_AR_MONTHS) + ")"
)
_Y = r"(?<!\d)(?:19|20)\d{2}(?!\d)"
_DATE = rf"(?:\d{{1,2}}\s*[/.]\s*{_Y}|(?:{_MON}\.?,?\s*)?{_Y})"
_PRESENT = (
    r"(?:حتى\s*الآن|حتي\s*الان|حتى\s*الان|الآن|الان|حاليا|حاليًا|حالياً|present|current(?:ly)?"
    r"|now|today|ongoing|till\s+date|to\s+date)"
)
_SEP = r"(?:[-–—]|(?<!\w)(?:to|until|till|إلى|الى|حتى|حتي)(?!\w))"
_RANGE = re.compile(
    rf"(?<!\w)(?P<a>{_DATE})\s*{_SEP}\s*(?P<b>{_DATE}|(?<!\w){_PRESENT}(?!\w))(?!\w)", re.I
)


def _parse_date(s: str) -> date | None:
    """Year-only means January: a year-only range never over-counts experience."""
    if m := re.fullmatch(r"(\d{1,2})\s*[/.]\s*((?:19|20)\d{2})", s.strip()):
        return date(int(m[2]), min(max(int(m[1]), 1), 12), 1)
    year = re.search(_Y, s)
    if not year:
        return None
    month = 1
    if word := re.search(_MON, s[: year.start()], re.I):
        w = word.group(0).lower()
        month = _AR_MONTHS.get(w) or _EN_ABBR.index(w[:3]) + 1
    return date(int(year.group(0)), month, 1)


# --- links and contacts ----------------------------------------------------------------

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w@])\+?\d[\d\s().-]{7,}\d")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>\"')\],;|]+", re.I)
_LINKEDIN = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/in/[\w%-]+", re.I)
_GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[\w-]+", re.I)
_NOT_PORTFOLIO = (
    "linkedin.com", "github.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "t.me", "wuzzuf.net", "indeed.com", "glassdoor.com", "bayt.com",
    "openxmlformats.org", "microsoft.com", "w3.org",
)  # fmt: skip


def _host(url: str) -> str:
    return re.sub(r"^(?:https?://)?(?:www\.)?", "", url.lower()).split("/")[0]


def _https(url: str) -> str:
    return url if url.lower().startswith("http") else "https://" + url


def cv_links(docx_path: Path) -> list[str]:
    """Hyperlink targets from the DOCX rels (document, headers, footers); [] for LaTeX."""
    if docx_path.suffix.lower() != ".docx":
        return []
    doc = Document(str(docx_path))
    out: list[str] = []
    for part in doc.part.package.iter_parts():
        if not re.match(r"^/word/(document|header\d*|footer\d*)\.xml$", str(part.partname)):
            continue
        out += [
            r.target_ref for r in part.rels.values() if r.is_external and r.reltype == RT.HYPERLINK
        ]
    return _dedupe(out)


def _phone_digits(raw: str) -> str:
    plus = "+" if raw.strip().startswith("+") else ""
    return plus + re.sub(r"\D", "", raw)


def _contacts(lines: list[str], links: Sequence[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    mail = next((x[7:].split("?")[0] for x in links if x.lower().startswith("mailto:")), "")
    tel = next((x[4:] for x in links if x.lower().startswith("tel:")), "")
    out["email"] = mail.strip() or next((m[0] for ln in lines if (m := _EMAIL.search(ln))), "")
    out["phone"] = _phone_digits(tel) if tel.strip() else ""
    if not out["phone"]:
        for ln in lines:
            if _RANGE.search(ln):
                continue
            for m in _PHONE.finditer(ln):
                if 9 <= len(re.sub(r"\D", "", m[0])) <= 15:
                    out["phone"] = _phone_digits(m[0])
                    break
            if out["phone"]:
                break
    sources = [*links, *lines]  # link targets first: the visible text is often just "LinkedIn"
    for key, rx in (("linkedin", _LINKEDIN), ("github", _GITHUB)):
        out[key] = next((_https(m[0]) for s in sources if (m := rx.search(s))), "")
    for s in sources:
        for m in _URL.finditer(s) if not s.lower().startswith(("mailto:", "tel:")) else []:
            url = m[0].rstrip(".")
            if not any(_host(url) == h or _host(url).endswith("." + h) for h in _NOT_PORTFOLIO):
                out["portfolio"] = _https(url)
                break
        if out.get("portfolio"):
            break
    return out


# --- name and location ---------------------------------------------------------------

_WORD = r"[^\W\d_]+"
_NAME_RX = re.compile(rf"{_WORD}(?:[ '.\-]{_WORD})*\.?")
_NAME_LABEL = re.compile(r"^(?:full name|name|الاسم)\s*[:：]\s*", re.I)
_NOT_NAME = {"curriculum vitae", "resume", "cv", "الملخص", "السيرة الذاتية"}


def _find_name(lines: list[str]) -> tuple[str, bool]:
    cands: list[str] = []
    for ln in lines[:5]:
        ln = _NAME_LABEL.sub("", ln).strip()
        words = ln.split()
        if (
            2 <= len(words) <= 5
            and _NAME_RX.fullmatch(ln)
            and ln.lower() not in _NOT_NAME
            and not _TITLE_RX.search(ln)
            and not _heading(ln)
        ):
            cands.append(ln)
    return (cands[0], len(cands) > 1) if cands else ("", False)


_PARTICLES = {"abd", "abdel", "abdul", "abdal", "abu", "el", "al", "bin", "ibn", "عبد", "أبو",
              "ابو", "بن", "ابن", "ال"}  # fmt: skip


def split_name(full_name: str) -> tuple[str, str]:
    """(first, last). A particle (Abdel, El, Bin, عبد ...) joins the token after it."""
    units: list[str] = []
    pending: list[str] = []
    for tok in full_name.split():
        pending.append(tok)
        if tok.lower().strip(".") not in _PARTICLES:
            units.append(" ".join(pending))
            pending = []
    if pending:  # trailing particle with nothing after it: keep it as a normal token
        units += pending
    if len(units) < 2:
        return (units[0], "") if units else ("", "")
    return units[0], units[-1]


_LOC_LABEL = re.compile(
    r"^(?:location|address|city|based in|العنوان|الموقع|المدينة)\s*[:：]\s*", re.I
)


def _find_location(lines: list[str]) -> str:
    for i, line in enumerate(lines):
        for frag in re.split(r"\s*[|•·;؛–—]\s*", line):
            labelled = bool(_LOC_LABEL.match(frag))
            frag = _LOC_LABEL.sub("", frag).strip(" ,،")
            if not frag or "@" in frag or "http" in frag.lower() or (not labelled and i >= 8):
                continue
            parts = [p.strip() for p in re.split(r"[,،]", frag) if p.strip()]
            if not parts or (not labelled and len(parts) < 2) or not _country(parts[-1]):
                continue
            if len(parts) > 2:  # street, city, country -> city, country
                parts = parts[-2:]
                frag = ", ".join(parts)
            if not any(ch.isdigit() for ch in frag):
                return frag
    return ""


# --- experience, education ---------------------------------------------------------------

_AT = re.compile(r"\s+(?:at|@|في|لدى)\s+", re.I)
_PIPE = re.compile(r"\s*[|•·]\s*|\s+[–—-]\s+")
_COMMA = re.compile(r"\s*[,،]\s*")


def _split_role(s: str) -> tuple[str, str]:
    """(title, company) from one line such as "Title at Company", "Company | Title"."""
    s = s.strip(_JUNK)
    if m := _AT.search(s):
        return s[: m.start()].strip(_JUNK), re.split(r"[,،|]", s[m.end() :])[0].strip(_JUNK)
    for rx in (_PIPE, _COMMA):
        parts = [p for p in (x.strip(_JUNK) for x in rx.split(s)) if p]
        if len(parts) > 2:
            parts = [p for p in parts if not _country(p)]
        if len(parts) >= 2:
            a, b = parts[0], parts[1]
            return (b, a) if _TITLE_RX.search(b) and not _TITLE_RX.search(a) else (a, b)
    return (s, "") if _TITLE_RX.search(s) else ("", s)


def _plain(line: str) -> bool:
    """A short non-bullet, non-date, non-heading line: a possible title/company neighbour."""
    return (
        len(line) <= 70
        and line[0] not in _BULLETS
        and not _RANGE.search(line)
        and not _heading(line)
        and "@" not in line
    )


def _experience_at(lines: list[str], i: int, m: re.Match[str]) -> Experience:
    line = lines[i]
    rest = (line[: m.start()].strip(_JUNK) or line[m.end() :].strip(_JUNK)) if line else ""
    title, company = _split_role(rest) if rest else ("", "")
    order = (i + 1, i - 1) if rest else (i - 1, i - 2, i + 1)
    near = [lines[j] for j in order if 0 <= j < len(lines) and _plain(lines[j])]
    # Fill what the date line did not say from the neighbouring lines; the UI flags the result.
    for n in near:
        if not title and _TITLE_RX.search(n):
            t, c = _split_role(n)
            title, company = t or c, company or (c if t else "")
        elif title and not company and not _TITLE_RX.search(n):
            company = _split_role(n)[1] or n.strip(_JUNK)
    for n in near:
        if not title and n.strip(_JUNK) != company:
            title = _split_role(n)[0] or n.strip(_JUNK)
        elif title and not company and n.strip(_JUNK) != title:
            company = _split_role(n)[1] or n.strip(_JUNK)
    if company and not title:
        title, company = company, ""
    b = m["b"]
    now = re.fullmatch(_PRESENT, b.strip(), re.I) is not None
    return Experience(
        title=title,
        company=company,
        start=_parse_date(m["a"]),
        end=None if now else _parse_date(b),
        current=now,
        intern=bool(_INTERN_RX.search(title)),
    )


def _experiences(lines: list[str]) -> list[Experience]:
    out: list[Experience] = []
    section: str | None = None
    for i, line in enumerate(lines):
        if sec := _heading(line):
            section = sec
            continue
        if section not in (None, "experience") or line[0] in _BULLETS or len(line) > 140:
            continue
        if m := _RANGE.search(line):
            exp = _experience_at(lines, i, m)
            if exp.start and exp not in out:
                out.append(exp)
    return out


_EDU_RX = re.compile(
    r"\b(?:b\.?sc|m\.?sc|b\.?eng|m\.?eng|ph\.?d|mba|bachelor|master|diploma|degree|associate"
    r"|university|college|institute|academy|school|faculty)\b"
    r"|بكالوريوس|ماجستير|دكتوراه|دبلوم|ليسانس|جامعة|كلية|معهد|أكاديمية",
    re.I,
)


def _education(lines: list[str]) -> list[str]:
    out: list[str] = []
    section: str | None = None
    for ln in lines:
        if sec := _heading(ln):
            section = sec
            continue
        if section != "education":
            continue
        ln = re.sub(r"\(\s*\)", "", re.sub(_Y, "", _RANGE.sub("", ln)))
        for part in re.split(r"\s*[|•·;]\s*|\s+[–—-]\s+|\s*[,،]\s*", ln):
            part = part.strip(_JUNK)
            if part and _EDU_RX.search(part):
                out.append(part)
    return _dedupe(out)


# --- skills ------------------------------------------------------------------------------

_TECH = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Golang", "Rust", "PHP", "Ruby",
    "Kotlin", "Swift", "SQL", "PostgreSQL", "MySQL", "MongoDB", "Redis", "SQLite", "FastAPI",
    "Django", "Flask", "Spring Boot", "Node.js", "React", "Angular", "Vue", "HTML", "CSS",
    "Tailwind", "Docker", "Kubernetes", "AWS", "Azure", "GCP", "Linux", "Git", "GitHub",
    "CI/CD", "Terraform", "Ansible", "Jenkins", "REST", "GraphQL", "Kafka", "RabbitMQ",
    "Elasticsearch", "Pandas", "NumPy", "TensorFlow", "PyTorch", "scikit-learn",
    "Machine Learning", "Deep Learning", "NLP", "Data Analysis", "Power BI", "Tableau",
    "Spark", "Hadoop", "Airflow", "ETL", "Selenium", "Playwright", "Pytest", "JUnit",
    "Flutter", "Android", "iOS", "React Native", ".NET", "ASP.NET", "Laravel", "Bash",
    "PowerShell", "Microservices", "DevOps", "Cybersecurity", "Networking", "Agile", "Scrum",
    "Jira", "Figma",
]  # fmt: skip
_GENERAL = [
    "Excel", "Microsoft Excel", "Microsoft Word", "PowerPoint", "Accounting", "Bookkeeping",
    "Auditing", "Financial Reporting", "Budgeting", "SAP", "Oracle", "QuickBooks", "Odoo",
    "Sales", "Negotiation", "Marketing", "SEO", "Social Media", "Content Writing",
    "Copywriting", "Customer Service", "Customer Support", "Communication", "Leadership",
    "Teamwork", "Project Management", "Recruitment", "Payroll", "Logistics", "Supply Chain",
    "Procurement", "Inventory", "Teaching", "Translation", "Photoshop", "Illustrator", "Canva",
    "Public Speaking", "Time Management", "Problem Solving", "Presentation", "Data Entry",
    "CRM", "Salesforce", "HubSpot", "Event Planning", "Administration", "Research",
    "Quality Control", "المحاسبة", "المبيعات", "خدمة العملاء", "إكسل", "بايثون",
]  # fmt: skip
_TECH_SET = {w.lower() for w in _TECH}
# Words that are also ordinary English: matched case-sensitively.
_CASE_SENSITIVE = {"Excel", "Rust", "Swift", "Oracle"}


def _lexicon_rx(words: list[str], flags: int) -> re.Pattern[str]:
    alt = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
    return re.compile(rf"(?<![\w.+#])(?:{alt})(?![\w+#])", flags)


_LEX = _TECH + _GENERAL
_LEX_CI = _lexicon_rx([w for w in _LEX if w not in _CASE_SENSITIVE], re.I)
_LEX_CS = _lexicon_rx([w for w in _LEX if w in _CASE_SENSITIVE], 0)


def _skills(lines: list[str]) -> list[str]:
    out: list[str] = []
    section: str | None = None
    for ln in lines:
        if sec := _heading(ln):
            section = sec
            continue
        if section != "skills":
            continue
        label, sep, rest = ln.partition(":")
        if sep and len(label) <= 30:  # "Languages: ..." is not a skill list; other labels are
            if label.lower().startswith(("language", "اللغات")):
                continue
            ln = rest
        for item in re.split(r"[,،;؛•|·▪●◦]|\s{2,}", ln):
            item = item.strip(" -–—*")
            if 1 < len(item) <= 40 and len(item.split()) <= 4:
                out.append(item)
    blob = "\n".join(lines)
    out += [m[0] for rx in (_LEX_CI, _LEX_CS) for m in rx.finditer(blob)]
    return _dedupe(out)


# --- reading a CV --------------------------------------------------------------------------


def read_cv(texts: list[str], links: Sequence[str] = ()) -> CvFacts:
    """Facts from CV segment texts (document order, headers/footers included)."""
    lines = _lines(texts)
    name, name_check = _find_name(lines)
    return CvFacts(
        full_name=name,
        name_check=name_check,
        location=_find_location(lines),
        experiences=_experiences(lines),
        education=_education(lines),
        skills=_skills(lines),
        **_contacts(lines, links),
    )


def _month_index(d: date) -> int:
    return d.year * 12 + d.month - 1


def years_experience(facts: CvFacts, today: date) -> int | None:
    """Whole years over the union of dated, non-intern ranges (overlaps counted once).

    None when no experience has dates. Internships do not count (decision Q2).
    """
    dated = [e for e in facts.experiences if e.start and (e.end or e.current)]
    if not dated:
        return None
    now = _month_index(today)
    spans = sorted(
        (_month_index(e.start), min(_month_index(e.end) if e.end else now, now))
        for e in dated
        if e.start and not e.intern
    )
    total, reach = 0, -1
    for a, b in spans:
        a = max(a, reach)
        if b > a:
            total += b - a
            reach = b
    return total // 12


# --- suggestions -----------------------------------------------------------------------------

# Seniority bands (ux-plan 4.2): years pick a band, a senior-sounding current title raises it.
_BANDS: list[list[str]] = [
    ["intern", "junior"],
    ["junior", "mid"],
    ["mid", "senior"],
    ["senior", "lead"],
    ["lead", "manager", "executive"],
]
# Title words that rule a job out when it is two or more bands away from the chosen band.
_BAND_WORDS = [["intern"], ["junior"], [], ["senior"], ["director", "vp", "head of"]]
_RAISE_RX = re.compile(
    r"\b(senior|sr\.?|lead|head|manager|director|principal|vp)\b|كبير|رئيس|مدير|أول", re.I
)
_SENIORITY_WORDS = {
    "senior",
    "junior",
    "lead",
    "sr",
    "jr",
    "principal",
    "head",
    "intern",
    "مبتدئ",
    "أول",
}
_TECH_TITLE_RX = re.compile(
    r"\b(engineer|developer|programmer|data|devops|qa|software|sre)\b|\bIT\b|مهندس برمجيات|مطور",
    re.I,
)
# ponytail: any other engineer still reads as tech; the track is a one-tap suggestion.
_NON_TECH_ENG_RX = re.compile(r"civil|mechanical|chemical|petroleum|structural|مدني|ميكانيك", re.I)


def _band(years: int | None, title: str) -> int | None:
    if years is None:
        return None
    band = 0 if years < 1 else 1 if years < 3 else 2 if years < 6 else 3 if years < 10 else 4
    return min(band + 1, 4) if _RAISE_RX.search(title) else band


def _query_of(title: str) -> str:
    title = re.sub(r"\(.*?\)", " ", re.sub(r"(?i)\bhead of\b", " ", title))
    words = [w for w in title.split() if w.lower().strip(".,") not in _SENIORITY_WORDS]
    return " ".join(words).strip(" -–—,،|")


def _newest_first(facts: CvFacts) -> list[Experience]:
    """Experiences, current first, then newest start first."""
    return sorted(facts.experiences, key=lambda e: (e.current, e.start or date.min), reverse=True)


def infer(facts: CvFacts, today: date) -> dict[str, InferredValue]:
    """Setup suggestions from CV facts. A key is omitted when the CV says nothing about it."""
    out: dict[str, InferredValue] = {}
    roles = _newest_first(facts)
    current = roles[0] if roles and roles[0].current else None

    def put(
        key: str, value: Any, source: Source = "cv", level: Level = "auto", check: bool = False
    ) -> None:
        if value not in ("", None, []):
            out[key] = InferredValue(value=value, source=source, level=level, check=check)

    put("profile.full_name", facts.full_name, check=facts.name_check)
    put("profile.email", facts.email)
    put("profile.phone", facts.phone)
    put("profile.location", facts.location)
    put("profile.skills", facts.skills)
    first, last = split_name(facts.full_name)
    put("answers.first_name", first)
    put("answers.last_name", last)
    if facts.location:
        parts = [p.strip() for p in re.split(r"[,،]", facts.location) if p.strip()]
        put("answers.city", parts[0])
        if code := _country(parts[-1]):
            country = code.title()
            put("answers.country", country)
            put("answers.authorized_countries", [country], "country", "suggest")
    if current:
        put("answers.current_company", current.company, check=True)
        put("answers.current_title", current.title, check=True)
    put("answers.linkedin", facts.linkedin)
    put("answers.github", facts.github)
    put("answers.portfolio", facts.portfolio)
    locked = [x for e in facts.experiences for x in (e.company, e.title)] + facts.education
    put("profile.locked_facts", _dedupe(locked))

    titles = [e.title for e in roles if e.title]
    if facts.skills or titles:
        recent = titles[0] if titles else ""
        tech_skills = sum(s.lower() in _TECH_SET for s in facts.skills)
        tech_title = bool(_TECH_TITLE_RX.search(recent)) and not _NON_TECH_ENG_RX.search(recent)
        put("track", "tech" if tech_skills >= 3 or tech_title else "general", level="suggest")
    # Internship titles only become queries when there is nothing else to search for.
    query_titles = [e.title for e in roles if e.title and not e.intern] or titles
    queries = _dedupe([q for t in query_titles if (q := _query_of(t))])[:5]
    put("search.queries", queries, level="suggest")

    years = years_experience(facts, today)
    put("answers.years_experience", years, "years")
    band = _band(years, current.title if current else (titles[0] if titles else ""))
    if band is not None:
        put("filters.seniority", _BANDS[band], "years")
        far = [w for i, ws in enumerate(_BAND_WORDS) if abs(i - band) >= 2 for w in ws]
        put("filters.title_exclude", far, "years")
    return out
