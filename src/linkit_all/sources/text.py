"""HTML -> plain text and normalization used by sources and dedupe."""

import hashlib
import html
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from selectolax.lexbor import LexborHTMLParser

_BLOCK = re.compile(r"\n\s*\n+")
_TRACKING = re.compile(
    r"^(utm_\w+|gh_src|ref|refs|referer|source|src|trk\w*|trackingid|refid|"
    r"lever-\w+|campaign|fbclid|gclid|mc_\w+|_hs\w+)$",
    re.I,
)
# Legal forms and group words that differ between sites for one employer
# ("Merck Group" on LinkedIn, "Merck KGaA" on Indeed).
_COMPANY_SUFFIX = re.compile(
    r"\b(inc|llc|ltd|limited|gmbh|kgaa|co|corp|corporation|plc|sa|ag|bv|nv|se|"
    r"s\.?a\.?e|group|holdings?)\b\.?",
    re.I,
)


def html_to_text(markup: str, escaped: bool = False) -> str:
    if escaped:
        markup = html.unescape(markup)
    tree = LexborHTMLParser(markup)
    for node in tree.css("script, style"):
        node.decompose()
    text = tree.body.text(separator="\n") if tree.body else tree.text(separator="\n")
    lines = (" ".join(line.split()) for line in text.splitlines())
    return _BLOCK.sub("\n\n", "\n".join(lines)).strip()


def normalize_url(url: str) -> str:
    """Canonical job URL: https, no www/fragment/tracking params, sorted query."""
    p = urlsplit(url.strip())
    host = (p.hostname or "").lower().removeprefix("www.")
    if p.port:
        host = f"{host}:{p.port}"
    query = sorted((k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k))
    return urlunsplit(("https", host, p.path.rstrip("/") or "/", urlencode(query), ""))


def norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text.lower()).split())


# A repost often differs only by a note the recruiter added: "(Urgent Hiring)", "URGENT - ...".
_TITLE_PARTS = re.compile(r"[()\[\]|:!]|\s[-–—]\s")  # noqa: RUF001 - real dashes
_TITLE_NOISE = frozenset(
    {
        "urgent", "urgently", "hiring", "immediate", "immediately", "asap", "now", "start",
        "joiner", "joiners", "required", "needed", "wanted", "apply", "new", "hot", "opening",
        "vacancy", "عاجل", "مطلوب", "فورا", "فوري",
    }
)  # fmt: skip


_GENDER_TAG = re.compile(r"\b[mfwdxh]\s*/\s*[mfwdxh](?:\s*/\s*[mfwdxh])?\b", re.I)  # (m/f/d)
_REQ_ID = re.compile(r"(?:(?:req|requisition|ref|reference|job|id|no|r|jr)\s+)*\d{3,}")
_TITLE_ABBREV = {
    "sr": "senior", "snr": "senior", "jr": "junior", "eng": "engineer", "engr": "engineer",
    "dev": "developer", "mgr": "manager", "rep": "representative", "spec": "specialist",
    "assoc": "associate", "asst": "assistant",
}  # fmt: skip


def title_key(title: str) -> str:
    """`norm(title)` as a recruiter would read it: no added note, requisition number or gender
    tag, abbreviations spelled out. For fuzzy matching, never shown."""
    parts = [norm(p) for p in _TITLE_PARTS.split(_GENDER_TAG.sub(" ", title))]
    kept = [
        " ".join(_TITLE_ABBREV.get(w, w) for w in p.split())
        for p in parts
        if p and not set(p.split()) <= _TITLE_NOISE and not _REQ_ID.fullmatch(p)
    ]
    return " ".join(kept) or norm(title)


def norm_company(name: str) -> str:
    # A name made only of suffix words ("Group Holdings SE") must not become "".
    return norm(_COMPANY_SUFFIX.sub(" ", name)) or norm(name)


def job_hash(title: str, company: str, location: str) -> str:
    key = f"{norm(title)}|{norm_company(company)}|{norm(location)}"
    return hashlib.sha256(key.encode()).hexdigest()
