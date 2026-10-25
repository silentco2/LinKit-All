"""Parsing helpers shared by source plugins: schema.org JobPosting pages, Next.js and Nuxt data,
HTML text, RSS feeds, and the words vendors use for workplace type and company names."""

import html
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html.entities import html5
from typing import Any
from urllib.parse import urljoin

from lxml import etree
from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Remote, from_iso, remote_from_text
from linkit_all.sources.common import strip_html
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import html_to_text

# --- workplace type, company names, language words ---

_MODES: dict[str, Remote] = {
    "remote": "remote",
    "hybrid": "hybrid",
    "onsite": "onsite",
    "on-site": "onsite",
    "on site": "onsite",
    "office": "onsite",
}
_RU_REMOTE = ("удал", "дистанц")  # remote in Russian: удалённо, удалённая, дистанционно


def mode(value: str | None) -> Remote | None:
    """A vendor's workplace-type word ("Hybrid", "ON_SITE", "Office") as our remote mode."""
    return _MODES.get((value or "").strip().lower().replace("_", "-"))


def name_from_slug(slug: str) -> str:
    """Display name for a board slug when the API gives none: "acme-corp" -> "Acme Corp"."""
    return slug.replace("-", " ").replace("_", " ").title()


def name_from_host(host: str) -> str:
    """Company name from a careers host: "jobs.acme.com" -> "Acme", "acme.eploy.net" -> "Acme"."""
    skip = ("www", "jobs", "careers", "career")
    labels = [p for p in host.lower().split(".") if p not in skip]
    return name_from_slug(labels[0] if labels else host)


def remote_ru(*texts: str | None) -> Remote | None:
    """`remote_from_text` that also reads the Russian words (удалённо, дистанционно, гибрид)."""
    joined = " ".join(t for t in texts if t).lower()
    if "гибрид" in joined:
        return "hybrid"
    return "remote" if any(w in joined for w in _RU_REMOTE) else remote_from_text(joined)


def ru_mode(*texts: str | None) -> Remote | None:
    """Work format from Russian or English words; the broadest arrangement named wins (a posting
    offering "hybrid / office, elsewhere remote" can be taken remotely)."""
    joined = " ".join(t for t in texts if t).lower()
    if any(w in joined for w in ("удал", "дистанц", "remote")):
        return "remote"
    if "гибрид" in joined or "hybrid" in joined:
        return "hybrid"
    if any(w in joined for w in ("офис", "на месте", "office")):
        return "onsite"
    return None


def rub_month(low: Any, high: Any) -> dict[str, Any]:
    """Salary fields for a monthly rouble range; empty when neither bound is a positive number."""
    lo = low if isinstance(low, int | float) and low > 0 else None
    hi = high if isinstance(high, int | float) and high > 0 else None
    if lo is None and hi is None:
        return {}
    return {
        "salary_min": lo or hi,
        "salary_max": hi or lo,
        "salary_currency": "RUB",
        "salary_interval": "month",
    }


def ats_of(apply_url: str | None, default: str) -> str:
    """The ATS behind an apply link ("workday", "greenhouse"...), else `default` (the board's or
    company's own name)."""
    found = detect(apply_url) if apply_url else None
    return found[0] if found else default


# --- text and links ---

_TAG = re.compile(r"</?[a-zA-Z][^>]*>")
_ID_TAIL = re.compile(r"[^/?#]+$")


def clean(text: Any) -> str:
    """Entities decoded and runs of whitespace collapsed."""
    return " ".join(html.unescape(str(text or "")).split())


def node_text(node: LexborNode | None) -> str:
    """The node's text with every run of whitespace (nbsp too) collapsed to one space."""
    return " ".join(node.text(deep=True).split()) if node is not None else ""


def next_element(node: LexborNode) -> LexborNode | None:
    """The next sibling that is an element (a server-rendered table is full of text nodes)."""
    sib = node.next
    while sib is not None and sib.tag == "-text":
        sib = sib.next
    return sib


def text_of(part: str | None) -> str:
    """A body that may be HTML or plain text, as plain text."""
    part = (part or "").strip()
    return strip_html(part) if _TAG.search(part) else part


def sections(*pairs: tuple[str, str | None]) -> str:
    """(heading, body) pairs as one plain-text description; an empty body drops its heading."""
    out = []
    for heading, body in pairs:
        if text := text_of(body):
            out.append(f"{heading}\n{text}" if heading else text)
    return "\n\n".join(out)


def distinct(items: list[str | None], sep: str = "; ") -> str:
    """The non-empty items, stripped and de-duplicated in order, joined with `sep`."""
    return sep.join(dict.fromkeys(i.strip() for i in items if i and i.strip()))


def first(data: dict[str, Any], *keys: str) -> str:
    """The first non-empty string among `keys` of `data`, else ""."""
    return next((str(data[k]) for k in keys if data.get(k)), "")


def last_segment(url: str) -> str:
    """The final path segment of a URL (the posting's id or slug)."""
    m = _ID_TAIL.search(url.split("?")[0].split("#")[0].rstrip("/"))
    return m.group(0) if m else ""


def links(page: str, base: str, keep: Callable[[str], bool]) -> list[str]:
    """Absolute, de-duplicated hrefs of the anchors whose raw href passes `keep`, in page order
    (a job card often links the same posting twice)."""
    found: dict[str, None] = {}
    for a in LexborHTMLParser(page).css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if href and keep(href):
            found[urljoin(base, href).split("#")[0]] = None
    return list(found)


# --- dates ---


def when(value: Any) -> datetime | None:
    """A posting date ("2026-07-14T13:34:41+00:00", "2026-07-01", "2026-07-01 10:00:00") as naive
    UTC; None when it is missing, unreadable or in the future (a vendor's placeholder)."""
    try:
        dt = from_iso(value.strip()) if isinstance(value, str) else None
    except ValueError:
        return None
    return dt if dt and dt <= datetime.now(UTC).replace(tzinfo=None) else None


def safe_date(value: Any) -> datetime | None:
    """A vendor's datePosted ("2026-06-11 00:00:00", "2026-06-16") as naive UTC; None if odd."""
    try:
        return from_iso(str(value).strip().replace(" ", "T", 1)) if value else None
    except ValueError:
        return None


def rfc_date(value: str | None) -> datetime | None:
    """An RSS pubDate ("Mon, 10 Aug 2026 16:40:02 +0200") as naive UTC."""
    try:
        dt = parsedate_to_datetime((value or "").strip())
    except (TypeError, ValueError):
        return None
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


# --- schema.org JobPosting pages -> stubs ---

_PLACEHOLDER = re.compile(r"\bUNAVAILABLE\b,?\s*")  # iCIMS fills unknown address parts with this


def ld_stub(
    posting: dict[str, Any],
    *,
    source: str,
    url: str,
    company: str,
    extra: dict[str, Any],
    escaped: bool = False,
) -> JobStub | None:
    """A schema.org JobPosting as a stub (None when it has no title). `company` is used when
    the posting names none; `escaped`: the vendor HTML-escapes the description markup."""
    stub = to_stub({**posting, "datePosted": None}, source, url, source)
    if not stub.title:
        return None
    org = posting.get("hiringOrganization")
    named = stub.company if isinstance(org, dict) and org.get("name") else company
    return stub.model_copy(
        update={
            "company": named,
            "description": strip_html(posting.get("description") or "", escaped=escaped),
            "posted_at": when(posting.get("datePosted")),
            "remote": stub.remote or remote_from_text(stub.location),
            "extra": {**stub.extra, **extra},
        }
    )


def _bound(value: Any) -> float | None:
    try:
        number = float(str(value).strip())
    except ValueError:
        return None
    return number if number > 0 else None


def _salary(p: dict[str, Any]) -> dict[str, Any]:
    """The posting with baseSalary bounds as plain numbers (vendors write "55000.00" or "")."""
    salary = p.get("baseSalary")
    value = salary.get("value") if isinstance(salary, dict) else None
    if not isinstance(value, dict):
        return p
    fixed = {
        **value,
        "minValue": _bound(value.get("minValue")),
        "maxValue": _bound(value.get("maxValue")),
    }
    return {**p, "baseSalary": {**salary, "value": fixed}}  # type: ignore[dict-item]


def posting_stub(
    page: str,
    *,
    source: str,
    url: str,
    board: str,
    id: str,
    company: str,
    escaped: bool = True,
    prep: Callable[[str], str] = str,
) -> JobStub | None:
    """The first JobPosting of `page` as a stub; None when the page has none or no title.
    `company` is the fallback when the posting names no hiring organisation; `escaped` means
    the description is HTML-escaped inside the JSON; `prep` rewrites the raw description."""
    found = job_postings(page)[:1]
    if not found:
        return None
    p = _salary({**found[0], "datePosted": None})
    stub = to_stub(p, source, url, source)
    org = p.get("hiringOrganization")
    org_name = (org.get("name") if isinstance(org, dict) else org) or ""
    location = ", ".join(x for x in _PLACEHOLDER.sub("", stub.location).split(", ") if x)
    if not stub.title:
        return None
    return stub.model_copy(
        update={
            "company": " ".join(str(org_name).split()) or company,
            "location": location,
            "description": html_to_text(prep(str(p.get("description") or "")), escaped=escaped),
            "posted_at": safe_date(found[0].get("datePosted")),
            "remote": stub.remote or remote_from_text(location),
            "extra": {**stub.extra, "board": board, "id": id},
        }
    )


def board_stub(page: str, *, source: str, url: str, id: str) -> JobStub | None:
    """The page's schema.org JobPosting as a stub; None without a title or an employer name
    (a posting with no company cannot be applied to or de-duplicated)."""
    found = job_postings(page)[:1]
    if not found:
        return None
    posting = found[0]
    org = posting.get("hiringOrganization")
    company = clean(org.get("name") if isinstance(org, dict) else org)
    title = clean(posting.get("title"))
    if not (company and title):
        return None
    stub = ld_stub(
        {**posting, "title": title}, source=source, url=url, company=company, extra={"id": id}
    )
    if stub is None:
        return None
    return stub.model_copy(
        update={"company": company, "remote": stub.remote or remote_from_text(title)}
    )


# --- Next.js and Nuxt page data ---

# The page pushes its data as self.__next_f.push([1,"..."]) chunks: JS string literals that,
# joined, form the RSC "flight" stream holding the page's JSON.
_PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
# A text row is "<hex id>:T<hex byte length>,<content>"; a posting refers to it as "$<id>".
_TEXT_ROW = re.compile(rb"[^0-9a-f]([0-9a-f]+):T([0-9a-f]+),")


def next_data(page: str) -> dict[str, Any] | None:
    """The `__NEXT_DATA__` JSON of a Next.js page, or None when it is missing or not JSON."""
    node = LexborHTMLParser(page).css_first("script#__NEXT_DATA__")
    try:
        data = json.loads(node.text(deep=True)) if node else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def decode_flight(page: str) -> str:
    """The joined RSC "flight" stream of a Next.js app-router page; ValueError when it has none."""
    chunks = _PUSH.findall(page)
    if not chunks:
        raise ValueError("deel: no Next.js flight payload on the page")
    return "".join(json.loads(c) for c in chunks)


def bracket_slice(text: str, key: str, open_: str, close: str) -> str | None:
    """The balanced open..close run after `key`, counting brackets outside string literals."""
    at = text.find(key)
    start = text.find(open_, at) if at >= 0 else -1
    if start < 0:
        return None
    depth, in_string, i = 0, False, start
    while i < len(text):
        c = text[i]
        if in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == open_:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
        i += 1
    return None


def text_rows(flight: str) -> dict[str, str]:
    """The flight's text rows by id; each row's content is exactly its declared number of bytes."""
    raw = flight.encode()
    rows = {}
    for m in _TEXT_ROW.finditer(raw):
        start = m.end()
        rows[m[1].decode()] = raw[start : start + int(m[2], 16)].decode(errors="replace")
    return rows


def unflatten(raw: list[Any]) -> Any:
    """Resolve a devalue array (Nuxt `_payload.json`): an object's values and an array's elements
    that are integers are indices into `raw`; other values are literal. A string-headed array is
    a type wrapper (e.g. ["ShallowReactive", 3]) and resolves to the value it wraps."""
    memo: dict[int, Any] = {}

    def hydrate(i: int) -> Any:
        if not 0 <= i < len(raw):
            return None
        if i in memo:
            return memo[i]
        memo[i] = None  # a reference cycle resolves to null instead of recursing forever
        tok = raw[i]
        out: Any = tok
        if isinstance(tok, dict):
            out = {k: ref(v) for k, v in tok.items()}
        elif isinstance(tok, list):
            if tok and isinstance(tok[0], str):
                out = ref(tok[1]) if len(tok) > 1 else None
            else:
                out = [ref(v) for v in tok]
        memo[i] = out
        return out

    def ref(v: Any) -> Any:
        return hydrate(v) if isinstance(v, int) and not isinstance(v, bool) else v

    return hydrate(0)


# --- RSS feeds ---

# Hardened: no entity resolution, no network. Feeds are third-party text, so recover from slips.
_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False, recover=True)
_DECL = re.compile(r"^\s*<\?xml[^>]*\?>")
_NAMED = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
_XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}


def _html_entity(m: re.Match[str]) -> str:
    """Feeds written by some static-site generators carry HTML names ("&rsquo;") outside CDATA,
    which XML rejects; swap them for the character."""
    name = m[1]
    return m[0] if name in _XML_ENTITIES else html5.get(name + ";", m[0])


def feed_items(xml: str) -> list[dict[str, str]]:
    """Each RSS `<item>` as {child tag without namespace: text}. Empty for text that is no feed."""
    text = _NAMED.sub(_html_entity, _DECL.sub("", xml))
    root = etree.fromstring(text.encode("utf-8"), _PARSER)
    if root is None:
        return []
    items = []
    for item in root.iter("item"):
        row: dict[str, str] = {}
        for child in item:
            if isinstance(child.tag, str):
                row.setdefault(
                    etree.QName(child).localname, "".join(str(t) for t in child.itertext()).strip()
                )
        items.append(row)
    return items


def body_text(raw: str) -> str:
    """A feed's description as text. Some feeds escape their markup twice ("&lt;p&gt;" with no
    "<" at all), so that case is unescaped once before the HTML is read."""
    return html_to_text(raw, escaped="<" not in raw and "&lt;" in raw)
