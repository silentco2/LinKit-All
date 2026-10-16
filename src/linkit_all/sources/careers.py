"""Any company careers page that no ATS plugin covers.

Order: JSON-LD JobPosting on the page -> links that look like job pages (each read through
JSON-LD, else page text + AI extraction when a provider is available, else the page title) ->
"unsupported". Every fetch is checked against robots.txt first (Http.allowed). Pages that
need a browser or answer with a bot challenge are reported as unsupported, never worked around.
"""

import re
from collections.abc import AsyncIterator
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel
from selectolax.lexbor import LexborHTMLParser

from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError, render
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import html_to_text, normalize_url

PAGE = 10  # job pages per checkpoint
MAX_LIST_PAGES = 4  # the careers page plus at most 3 "next" pages
MAX_TEXT = 6000  # characters of page text sent to the model
MIN_TEXT = 200  # a listing with less text and no job links is almost surely JS-rendered

_JOB_PATH = re.compile(
    r"/(?:jobs?|positions?|vacanc(?:y|ies)|openings?|opportunit(?:y|ies)|apply)(?:/|$)"
    r"|/careers?/[^/]*(?:-|\d)[^/]*/?$",  # /careers/<slug>, but not /careers/benefits
    re.I,
)
_NOT_JOB = re.compile(r"/(?:login|sign-?in|sign-?up|privacy|terms|cookies?|search|alerts?)\b", re.I)
_FILE = re.compile(r"\.(?:pdf|docx?|jpe?g|png|gif|svg|css|js|xml|zip)$", re.I)
_ROLE = re.compile(
    r"\b(?:engineer|developer|manager|analyst|designer|scientist|architect|specialist|"
    r"consultant|director|officer|coordinator|administrator|technician|intern|associate|"
    r"recruiter|accountant|assistant|representative|executive|researcher|lead)\b",
    re.I,
)
_NEXT_TEXT = {"next", "next page", "next »", "›", "»", "older", "more jobs", "load more"}  # noqa: RUF001
_CHALLENGE = re.compile(
    r"just a moment|attention required|verify you are human|are you a robot|captcha|cf-chl", re.I
)
_SECOND_LEVEL = {"co", "com", "org", "gov", "ac", "net"}


class Unsupported(Exception):
    """This careers page cannot be read here; the message is shown to the user."""


class ExtractedJob(BaseModel):
    title: str
    location: str = ""
    remote: Literal["remote", "hybrid", "onsite"] | None = None
    employment_type: str = ""
    posted_date: str | None = None


def _site(url: str) -> str:
    """Registrable domain, good enough without a public-suffix list (example.co.uk)."""
    parts = (urlsplit(url).hostname or "").split(".")
    keep = 3 if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL else 2
    return ".".join(parts[-keep:])


def _looks_like_job(url: str, text: str) -> bool:
    path = urlsplit(url).path
    if _NOT_JOB.search(path) or _FILE.search(path):
        return False
    return bool(_JOB_PATH.search(path)) or (8 <= len(text) <= 120 and bool(_ROLE.search(text)))


def _is_next(rel: str, text: str) -> bool:
    return "next" in rel.lower().split() or text.lower() in _NEXT_TEXT


def _company(tree: LexborHTMLParser, url: str) -> str:
    meta = tree.css_first('meta[property="og:site_name"]')
    name = (meta.attributes.get("content") if meta else "") or ""
    return name.strip() or _site(url).split(".")[0].title()


def _title(tree: LexborHTMLParser) -> str:
    h1, title = tree.css_first("h1"), tree.css_first("title")
    return " ".join(((h1.text() if h1 else "") or (title.text() if title else "")).split())


def _main_text(html: str) -> str:
    import trafilatura  # heavy import, only needed for pages without JSON-LD

    return trafilatura.extract(html, include_comments=False) or html_to_text(html)


def _with_company(stub: JobStub, company: str) -> JobStub:
    return stub.model_copy(update={"company": company}) if stub.company == "Unknown" else stub


class Careers(Source):
    name = "careers"
    priority = 3  # after the ATS APIs and site plugins, which have cleaner data

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        url = task.board
        html = await self._fetch(http, url)
        company = _company(LexborHTMLParser(html), url)
        if postings := job_postings(html):
            if start_page == 0:  # ponytail: postings without their own url share the page url
                stubs = [to_stub(p, self.name, p.get("url") or url, None) for p in postings]
                yield [_with_company(s, company) for s in stubs[: task.limit]]
            return
        links = await self._job_links(http, url, html, task.limit)
        if not links:
            raise Unsupported(
                "needs a browser; not supported yet"
                if len(html_to_text(html)) < MIN_TEXT
                else "no job postings or job links found"
            )
        for start in range(start_page * PAGE, len(links), PAGE):
            found = [await self._job(http, link, company) for link in links[start : start + PAGE]]
            yield [s for s in found if s is not None]

    async def _fetch(self, http: Http, url: str) -> str:
        if not await http.allowed(url):
            raise Unsupported(f"robots.txt does not allow fetching {url}")
        resp = await http.get(url)
        title = LexborHTMLParser(resp.text).css_first("title")
        if _CHALLENGE.search(title.text() if title else "") or (
            resp.status_code >= 400 and _CHALLENGE.search(resp.text[:5000])
        ):
            raise Unsupported("the site answered with a bot challenge; it is not bypassed")
        resp.raise_for_status()
        return resp.text

    async def _job_links(self, http: Http, url: str, html: str, limit: int) -> list[str]:
        links: dict[str, str] = {}
        seen = {normalize_url(url)}
        for page in range(MAX_LIST_PAGES):
            nxt = ""
            for a in LexborHTMLParser(html).css("a[href]"):
                href = urljoin(url, (a.attributes.get("href") or "").strip()).split("#")[0]
                if not href.startswith("http") or _site(href) != _site(url):
                    continue
                text = " ".join(a.text().split())
                if _is_next(a.attributes.get("rel") or "", text):
                    nxt = nxt or href
                elif normalize_url(href) not in seen and _looks_like_job(href, text):
                    links.setdefault(normalize_url(href), href)
            if (
                page == MAX_LIST_PAGES - 1
                or len(links) >= limit
                or not nxt
                or normalize_url(nxt) in seen
            ):
                break
            seen.add(normalize_url(nxt))
            try:
                html, url = await self._fetch(http, nxt), nxt
            except Unsupported:  # robots or challenge on page 2+: keep what page 1 gave
                break
        return list(links.values())[:limit]

    async def _job(self, http: Http, url: str, company: str) -> JobStub | None:
        if not await http.allowed(url):
            return None
        try:
            html = await self._fetch(http, url)
        except (httpx.HTTPError, RetryableStatus):  # a dead link must not sink the page
            return None
        if postings := job_postings(html):
            return _with_company(to_stub(postings[0], self.name, url, None), company)
        title, text = _title(LexborHTMLParser(html)), _main_text(html)
        found = await self._extract(text)
        posted = None
        if found and found.posted_date:
            try:
                posted = from_iso(found.posted_date)
            except ValueError:
                posted = None
        location = found.location if found else ""
        return JobStub(
            source=self.name,
            url=url,
            title=(found.title if found and found.title else title) or url,
            company=company,
            location=location,
            description=text,
            posted_at=posted,
            apply_url=url,
            remote=(found.remote if found else None) or remote_from_text(title, location),
            extra={"employment": found.employment_type} if found else {},
        )

    async def _extract(self, text: str) -> ExtractedJob | None:
        if self.provider is None:
            return None
        try:
            return await self.provider.complete(
                render("extract_job.j2", text=text[:MAX_TEXT]), ExtractedJob
            )
        except UsageLimitError:
            raise  # pause the run cleanly instead of silently degrading
        except ProviderError:
            return None
