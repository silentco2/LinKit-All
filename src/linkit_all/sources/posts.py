# ruff: noqa: RUF001, RUF002  (Cyrillic and Arabic words are the point here)
"""Reading a job post (Telegram, LinkedIn) by script: no AI at any step.

An email in the post makes it an email application; otherwise its first job link goes to the
careers scraper (one page, no AI), which may add the details the page states. A post with neither
yields no job. Which of several jobs a post lists is not told apart: one post, one job.
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from loguru import logger

from linkit_all.core import geo
from linkit_all.core.search import SearchConfig
from linkit_all.sources.base import JobStub, Remote, remote_from_text
from linkit_all.sources.careers import Careers
from linkit_all.sources.http import Http

_MARKS = re.compile("[ؐ-ًؚ-ٰٟـ]")  # Arabic diacritics, tatweel
_LETTERS = str.maketrans("أإآٱةىئؤ", "ااااهييو")


def fold(text: str) -> str:
    """Lower case; Arabic alef forms -> ا, ة -> ه, ى/ئ -> ي, ؤ -> و; diacritics and tatweel gone."""
    return _MARKS.sub("", text.translate(_LETTERS)).lower()


_SEEKER = re.compile(
    fold(
        "|".join(
            (
                r"#opentowork|#open_to_work|open to work|open for work|open to new opportunit",
                r"(?:i am|i'm|im) (?:currently )?(?:actively )?(?:looking|searching|seeking) "
                r"(?:for )?(?:a |an )?(?:new )?(?:job|role|position|opportunit|work|employment)",
                r"(?:looking|searching|seeking) for (?:a |my )(?:new )?(?:job|role|position|"
                r"opportunit)",
                r"ابحث عن (?:عمل|وظيفة|فرصة|شغل)|أبحث عن (?:عمل|وظيفة|فرصة|شغل)",
                r"ابحث عن فرص",
                r"ищу работу|ищу вакансию|ищу стажировку|ищу удал[её]нную работу",
            )
        )
    )
)


def is_seeker(text: str) -> bool:
    return _SEEKER.search(fold(text.replace("’", "'"))) is not None


_EMAIL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
_ASSET_TLDS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "bmp", "ico", "css", "js", "pdf", "mp4"}
_URL = re.compile(
    r"(?:https?://|(?<![\w@./-])(?:www\.|lnkd\.in/|bit\.ly/))[^\s<>\"'؀-ۿ]+",
    re.IGNORECASE,
)
_TRAIL = ".,;:!?)]}>»'\"…"


def find_emails(text: str) -> tuple[str, ...]:
    """Distinct, lower-cased addresses in order of appearance. Trailing punctuation is not part
    of an address; `logo@2x.png` style asset names are not addresses."""
    found: dict[str, None] = {}
    for m in _EMAIL.finditer(text):
        mail = m.group(0).rstrip(_TRAIL).lower()
        domain = mail.partition("@")[2]
        if domain.rsplit(".", 1)[-1] in _ASSET_TLDS or re.fullmatch(r"\d+x", domain.split(".")[0]):
            continue
        found[mail] = None
    return tuple(found)


def find_links(text: str) -> tuple[str, ...]:
    """Distinct URLs in order of appearance (scheme added to bare www., short, acme.com/x)."""
    found: dict[str, None] = {}
    for m in sorted((*_URL.finditer(text), *_BARE_URL.finditer(text)), key=lambda m: m.start()):
        url = m.group(0).rstrip(_TRAIL)
        if not url.lower().startswith("http"):
            url = "https://" + url
        found[url] = None
    return tuple(found)


_BARE_URL = re.compile(
    r"(?<![\w@./-])(?:[a-z0-9-]+\.)+(?:com|net|org|io|co|ai|jobs|careers|app|ru|eg|sa|ae|uk|de)"
    r"/[^\s<>\"'؀-ۿ]+",
    re.IGNORECASE,
)
DESCRIPTION = 4000  # characters of a post kept as the job description
MAX_TITLE = 120
MIN_POST_TEXT = 200  # a shorter post says too little: the linked page's text describes the job
_NOT_JOB_HOSTS = (
    "t.me", "telegram.me", "telegram.org", "youtube.com", "youtu.be", "instagram.com",
    "facebook.com", "fb.com", "vk.com", "x.com", "twitter.com", "tiktok.com", "wa.me",
    "whatsapp.com", "zoom.us",
)  # fmt: skip
_FREE_MAIL = {
    "gmail", "googlemail", "yahoo", "outlook", "hotmail", "live", "icloud", "proton", "protonmail",
    "aol", "mail", "yandex", "gmx", "inbox", "bk", "list", "rambler",
}  # fmt: skip
_AD_LINE = re.compile(fold(r"реклам|сотрудничеств|advertis|promo|sponsor|إعلان|اعلان"))
_REMOTE = re.compile(fold(r"удален|удалён|عن بعد|من المنزل"))
_LABEL = re.compile(
    r"^\s*(?:tl;dr|vacancy|position|role|job title|job|title|вакансия|должность|позиция|"
    r"الوظيفة|المسمى الوظيفي)\s*[:：–—-]\s*(.+)$",
    re.IGNORECASE,
)
_COMPANY = re.compile(
    r"^\s*(?:company|employer|empresa|компания|работодатель|الشركة)\s*[:：–—-]\s*(.+)$",
    re.IGNORECASE,
)
_NOISE = re.compile(r"https?://\S+|\S+@\S+\.\S+|(?<![\w+])#\w+")
_WANTED = re.compile(r"^(?:مطلوب|وظيفة)\s+")
_CONTACT_TAIL = re.compile(
    r"(?:[,.;:!–—]|\s-)\s*(?:send|apply|email|e-mail|contact|dm|reach|отправ|присыл|пишите|"
    r"ارسل|أرسل|للتقديم).*$",
    re.IGNORECASE,
)
_EDGES = re.compile(r"^[^\w(]+|[^\w)+#]+$")


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _on(host: str, sites: tuple[str, ...]) -> bool:
    return any(host == s or host.endswith("." + s) for s in sites)


def _clean(line: str) -> str:
    """A title out of one line of a post; '' when nothing is left."""
    line = _WANTED.sub("", _NOISE.sub(" ", line).strip())
    return _EDGES.sub("", " ".join(_CONTACT_TAIL.sub("", line).split()))[:MAX_TITLE]


def heading(text: str, words: tuple[str, ...] = ()) -> str:
    """The job title of a post: a labelled line ("Position: X"), else the first line naming one of
    the user's title words, else the first line with any words on it."""
    lines = text.splitlines()
    for line in lines:
        if (m := _LABEL.match(line)) and (title := _clean(m.group(1))):
            return title
    wanted = [fold(w) for w in words if w.strip()]
    for line in lines:
        if any(w in fold(line) for w in wanted) and (title := _clean(line)):
            return title
    return next((title for line in lines if (title := _clean(line))), "")


def contact_email(text: str) -> str:
    """The address to apply to; a channel's own advertising contact does not count."""
    for line in text.splitlines():
        if not _AD_LINE.search(fold(line)) and (found := find_emails(line)):
            return found[0]
    return ""


def company_of(text: str, email: str) -> str:
    """The company a post states, else the name in a company email address, else "Unknown"."""
    for line in text.splitlines():
        if (m := _COMPANY.match(line)) and (name := _EDGES.sub("", m.group(1).strip())):
            return name[:80]
    labels = email.partition("@")[2].split(".")
    if len(labels) < 2:
        return "Unknown"
    name = (
        labels[-3] if len(labels) > 2 and labels[-2] in ("co", "com", "org", "net") else labels[-2]
    )
    return "Unknown" if name in _FREE_MAIL else name.title()


def job_link(links: tuple[str, ...]) -> str:
    """The first link that can be a job page: not social, not a bare home page."""
    for url in links:
        host = _host(url)
        path = urlsplit(url).path if host else ""
        if not host or _on(host, _NOT_JOB_HOSTS) or path in ("", "/"):
            continue
        if _on(host, ("linkedin.com",)) and "/jobs" not in path:
            continue
        return url
    return ""


@dataclass(frozen=True)
class PostRules:
    """What the post readers need from the user's search."""

    title_words: tuple[str, ...] = ()
    places: tuple[str, ...] = ()
    never_fetch: tuple[str, ...] = ()  # ban-risk sites: linked to, never read

    @classmethod
    def of(cls, cfg: SearchConfig) -> "PostRules":
        return cls(
            tuple(cfg.filters.title_include),
            tuple(cfg.filters.locations),
            tuple(cfg.apply.assisted_hosts),
        )

    def place(self, text: str) -> str:
        """The configured place a post names ("Cairo" or its Arabic name find "cairo, egypt"),
        else ''. Every place's city is tried before any country, so Alexandria beats "egypt"."""
        folded = fold(text)

        def named(part: str) -> bool:
            return any(
                re.search(rf"(?<!\w){re.escape(fold(n))}(?!\w)", folded)
                for n in (part, geo.arabic_name(part))
                if n
            )

        rows = [(loc, [p.strip() for p in loc.split(",") if p.strip()]) for loc in self.places]
        for loc, parts in rows:
            if parts and named(parts[0]):
                return loc
        return next((loc for loc, parts in rows if any(named(p) for p in parts[1:])), "")

    def worth_reading(self, text: str) -> bool:
        """Could this post pass the user's title and place filters? If not, its link is not
        read. ponytail: a post silent on both whose page names them is missed."""
        folded = fold(text)
        wanted = [fold(w) for w in self.title_words if w.strip()]
        if wanted and not any(w in folded for w in wanted):
            return False
        return not self.places or bool(self.place(text))


@dataclass(frozen=True)
class PostJob:
    source: str
    url: str  # the post: the dedupe key
    text: str
    links: tuple[str, ...]
    posted_at: datetime | None
    extra: dict[str, Any]


def _remote(text: str) -> Remote | None:
    return remote_from_text(text) or ("remote" if _REMOTE.search(fold(text)) else None)


async def post_stub(
    http: Http, reader: Careers, post: PostJob, rules: PostRules, *, fetch: bool = True
) -> JobStub | None:
    """The job in a post (no AI), or None when it gives no way to apply. `fetch` False: use the
    post alone (it is stored already)."""
    email = contact_email(post.text)
    link = "" if email else job_link(post.links)
    title = heading(post.text, rules.title_words)
    if not title or not (email or link):
        return None
    stub = JobStub(
        source=post.source,
        url=post.url,
        title=title,
        company=company_of(post.text, email),
        location=rules.place(post.text),
        description=post.text[:DESCRIPTION],
        posted_at=post.posted_at,
        apply_url=f"mailto:{email}" if email else link,
        remote=_remote(post.text),
        extra=post.extra,
    )
    readable = link and fetch and rules.worth_reading(post.text)
    if not readable or _on(_host(link), rules.never_fetch):
        return stub
    try:
        read = await reader.read_job(http, link)
    except Exception as e:  # blocked, offline, odd page: the post itself is still a job
        logger.debug("job link {} not read: {}", link, type(e).__name__)
        return stub
    if read is None:
        return stub
    page, structured = read
    short = len(post.text) < MIN_POST_TEXT
    return stub.model_copy(
        update={
            "title": page.title if structured and page.title else title,
            "company": page.company if structured and page.company != "Unknown" else stub.company,
            "location": page.location or stub.location,
            "description": (page.description if structured or short else post.text)[:DESCRIPTION]
            or stub.description,
            "posted_at": (page.posted_at if structured else None) or stub.posted_at,
            "remote": page.remote or stub.remote,
            "salary_min": page.salary_min,
            "salary_max": page.salary_max,
            "salary_currency": page.salary_currency,
            "salary_interval": page.salary_interval,
        }
    )
