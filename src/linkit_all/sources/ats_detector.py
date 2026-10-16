"""Route a pasted career URL (or page HTML) to the ATS that hosts its jobs."""

import re

SUPPORTED = {"greenhouse", "lever", "ashby", "smartrecruiters", "recruitee", "workable", "workday"}

# Order matters: the Greenhouse embed form must win over the plain board form.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("greenhouse", re.compile(r"greenhouse\.io/embed/job_board(?:/js)?\?for=([\w-]+)", re.I)),
    ("greenhouse", re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/([\w-]+)", re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/([\w-]+)", re.I)),
    ("lever", re.compile(r"jobs(?:\.eu)?\.lever\.co/([\w.-]+)", re.I)),
    ("lever", re.compile(r"api(?:\.eu)?\.lever\.co/v0/postings/([\w.-]+)", re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)", re.I)),
    # Workday slug is "tenant/wdN/site"; the locale segment (en-US) is not part of it.
    (
        "workday",
        re.compile(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/wday/cxs/[\w-]+/([\w-]+)", re.I),
    ),
    (
        "workday",
        re.compile(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)"),
    ),
    (
        "smartrecruiters",
        re.compile(r"smartrecruiters\.com/(?:oneclick-ui/company|v1/companies)/([\w-]+)", re.I),
    ),
    ("smartrecruiters", re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/api/v\d/(?:widget/)?accounts/([\w-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)", re.I)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.I)),
]
_SHORTHAND = re.compile(
    r"^(greenhouse|lever|ashby|workday|smartrecruiters|workable|recruitee):(.+)$"
)
_NOT_SLUGS = {"embed", "v1", "jobs", "api", "www", "oneclick-ui"}


def detect(text: str) -> tuple[str, str] | None:
    """(ats, board slug) from a URL, "ats:slug" shorthand, or any text such as page HTML."""
    if m := _SHORTHAND.match(text.strip()):
        return m.group(1), m.group(2)
    for ats, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            if m.group(1).lower() not in _NOT_SLUGS:
                return ats, "/".join(m.groups())
    return None
