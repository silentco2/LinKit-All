"""Is a posting closed, read from the page's own words? Shared by the ATS handlers and the form
agent. The text is normalised first (typographic quotes, accents, case, spacing), because sites
write "n'est plus disponible" with a typographic apostrophe (U+2019) and a pattern spelled with
an ASCII one never matched it. Only clear closure wording counts; "the form has been filled out"
does not. Logic adapted from career-ops (MIT)."""

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

# typographic single quotes, the modifier apostrophe and the acute accent -> ', curly doubles -> "
_QUOTES = str.maketrans(
    {chr(c): "'" for c in (0x2018, 0x2019, 0x02BC, 0x00B4)}
    | {chr(c): '"' for c in (0x201C, 0x201D, 0x00AB, 0x00BB)}
)
_ARABIC = (chr(0x0600), chr(0x06FF))
_JOB = r"(?:job|position|posting|vacancy|ad|role|listing|opening|requisition|req)"

_CLOSED = re.compile(
    "|".join(
        [
            # English
            r"^404\b|\b(?:error 404|404 error|page not found)\b",
            r"\bno longer (?:available|accepting(?: applications)?|open|active|online)\b",
            rf"\b(?:this|the) {_JOB} (?:has )?(?:expired|closed|been closed|been removed)\b",
            rf"\b{_JOB} (?:you are (?:trying to apply for|looking for) )?has been filled\b",
            r"\b(?:the )?(?:position|role|job) (?:was|has been|is) filled\b",
            r"\bapplications? (?:are|is) (?:now )?closed\b|\bnot accepting applications\b",
            # French
            r"\b(?:cette|l') ?offre "
            r"(?:n'est plus (?:disponible|active|en ligne)|a expire|est expiree|est pourvue)",
            r"\bposte (?:a ete )?pourvu\b|\bcandidatures? (?:sont )?closes?\b",
            # German
            r"\b(?:stelle|stellenanzeige|anzeige) (?:ist )?"
            r"(?:nicht mehr (?:verfugbar|aktiv|online)|bereits besetzt|besetzt|abgelaufen)",
            r"\bnicht mehr verfugbar\b",
            # Spanish
            r"\b(?:esta |la )?(?:oferta|vacante|posicion) (?:ya )?"
            r"(?:no esta disponible|ha (?:expirado|caducado|sido cubierta)|esta cerrada|cerrada)",
            r"\bya no (?:esta disponible|acepta (?:candidaturas|solicitudes))\b",
            # Arabic
            r"(?:الوظيفة|هذه الوظيفة|الإعلان) "
            r"(?:لم تعد متاحة|لم يعد متاحا|انتهت|منتهية|مغلقة|تم شغلها)",
            r"انتهى (?:التقديم|الإعلان)|تم إغلاق (?:التقديم|الوظيفة)",
        ]
    ),
    re.I | re.M,
)
# "has been filled" about a form, or "filled out", is not a filled vacancy
_NOT_CLOSED = re.compile(
    r"\b(?:application|form|field|fields|section|profile) (?:has been|was|is) filled\b"
    r"|\bfilled out\b",
    re.I,
)


def normalise(text: str) -> str:
    """ASCII quotes, no diacritics (Arabic letters kept), one space between words."""
    text = unicodedata.normalize("NFKD", text.translate(_QUOTES))
    low, high = _ARABIC
    text = "".join(ch for ch in text if not unicodedata.combining(ch) or low <= ch <= high)
    return " ".join(text.split())


def closed_text(text: str) -> bool:
    """True when the page says the posting is closed, expired, filled or not found."""
    plain = normalise(text)
    for m in _CLOSED.finditer(plain):
        around = plain[max(0, m.start() - 40) : m.end() + 15]
        if not _NOT_CLOSED.search(around):
            return True
    return False


def workday_listing(url: str) -> str | None:
    """A Workday `/apply` link (often from a promoted post, with tracking parameters) can 404
    while the posting is live: the listing URL without `/apply` and the query to try instead.
    None when `url` is not such a link."""
    parts = urlsplit(url)
    if "myworkdayjobs.com" not in parts.netloc and "myworkdaysite.com" not in parts.netloc:
        return None
    path = re.sub(r"/apply(?:/[^/]*)?/?$", "", parts.path)
    if path == parts.path and not parts.query:
        return None
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))
