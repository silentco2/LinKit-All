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
_COMPANY_SUFFIX = re.compile(
    r"\b(inc|llc|ltd|limited|gmbh|co|corp|corporation|plc|sa|ag|bv|s\.?a\.?e)\b\.?", re.I
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


def norm_company(name: str) -> str:
    return norm(_COMPANY_SUFFIX.sub(" ", name))


def job_hash(title: str, company: str, location: str) -> str:
    key = f"{norm(title)}|{norm_company(company)}|{norm(location)}"
    return hashlib.sha256(key.encode()).hexdigest()
