"""Any company careers page that no ATS plugin covers.

Order: JSON-LD JobPosting on the page -> links that look like job pages (each read through
JSON-LD, else an <h1> plus a plainly labelled location, else page text sent to the AI in
batches of AI_BATCH pages per call when a provider is available, else the page title) ->
"unsupported". Every fetch is checked against robots.txt first (Http.allowed). A page with no
jobs in its HTML is then opened in Chrome when a provider is available (browser_extract: the AI
picks JSON-LD, a background JSON response or CSS selectors, our code runs it). Pages that still
give nothing, or answer with a bot challenge, are reported as unsupported, never worked around.
"""

import re
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin, urlsplit

import httpx
from playwright.async_api import Request, Route
from pydantic import BaseModel
from selectolax.lexbor import LexborHTMLParser

from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError, render
from linkit_all.sources.base import JobStub, Source, Task, from_iso, remote_from_text
from linkit_all.sources.browser_extract import (
    BrowserError,
    BrowserExtractor,
    Challenge,
    is_challenge,
    site,
)
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import html_to_text, normalize_url

PAGE = 10  # job pages per checkpoint
MAX_LIST_PAGES = 4  # the careers page plus at most 3 "next" pages
AI_BATCH = 10  # job pages per AI call; PAGE == AI_BATCH so one checkpoint costs at most one call
EXCERPT = 1500  # characters of each page's text sent to the model
MAX_LOCATION = 80  # a longer "Location:" value is prose, not a location
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
CHALLENGE_MESSAGE = "the site answered with a bot challenge; it is not bypassed"


class Unsupported(Exception):
    """This careers page cannot be read here; the message is shown to the user."""


class ExtractedJob(BaseModel):
    id: int  # our page number in the batch; replies with other ids are ignored
    title: str = ""
    location: str = ""
    remote: Literal["remote", "hybrid", "onsite"] | None = None
    employment_type: str = ""
    posted_date: str | None = None


class ExtractedBatch(BaseModel):
    jobs: list[ExtractedJob]


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
    return name.strip() or site(url).split(".")[0].title()


def _title(tree: LexborHTMLParser) -> str:
    h1, title = tree.css_first("h1"), tree.css_first("title")
    return " ".join(((h1.text() if h1 else "") or (title.text() if title else "")).split())


_LOCATION_LABEL = re.compile(r"^locations?\s*:\s*(.*)$", re.I)
_LOCATION_META = (
    'meta[name="geo.placename"]',
    'meta[property="og:locality"]',
    '[itemprop="addressLocality"]',
    '[itemprop="jobLocation"]',
)


def _location(tree: LexborHTMLParser) -> str:
    """A location the page states plainly (meta, microdata, a short "Location:" label), else ''."""
    for sel in _LOCATION_META:
        node = tree.css_first(sel)
        if node and (value := " ".join((node.attributes.get("content") or node.text()).split())):
            return value[:MAX_LOCATION]
    tree.strip_tags(["script", "style"])
    body = tree.body.text(separator="\n") if tree.body else ""
    lines = [ln for raw in body.splitlines() if (ln := raw.strip())]
    for i, line in enumerate(lines):
        if m := _LOCATION_LABEL.match(line):
            value = m.group(1) or (lines[i + 1] if i + 1 < len(lines) else "")
            if 2 <= len(value) <= MAX_LOCATION:
                return value
    return ""


def _main_text(html: str) -> str:
    import trafilatura  # heavy import, only needed for pages without JSON-LD

    return trafilatura.extract(html, include_comments=False) or html_to_text(html)


def _with_company(stub: JobStub, company: str) -> JobStub:
    return stub.model_copy(update={"company": company}) if stub.company == "Unknown" else stub


class Careers(Source):
    name = "careers"
    kind = "careers"
    priority = 3  # after the ATS APIs and site plugins, which have cleaner data

    def __init__(
        self,
        provider: LLMProvider | None = None,
        data_dir: Path | None = None,
        route: Callable[[Route, Request], Awaitable[None]] | None = None,
    ) -> None:
        self.provider = provider
        # The browser fallback needs a provider (it picks the extraction method) and a folder for
        # the recipe cache. `route` answers the browser's requests in tests.
        self._browser = (
            BrowserExtractor(provider, data_dir / "careers", route)
            if provider and data_dir
            else None
        )

    async def aclose(self) -> None:
        if self._browser is not None:
            await self._browser.close()

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
            found = (await self._rendered(http, url))[: task.limit]
            if not found:
                raise Unsupported(
                    "needs a browser; not supported yet"
                    if len(html_to_text(html)) < MIN_TEXT
                    else "no job postings or job links found"
                )
            for start in range(start_page * PAGE, len(found), PAGE):
                yield await self._finish(http, found[start : start + PAGE], company)
            return
        for start in range(start_page * PAGE, len(links), PAGE):
            yield await self._jobs(http, links[start : start + PAGE], company)

    async def _rendered(self, http: Http, url: str) -> list[JobStub]:
        """Jobs read from the page as Chrome draws it ([] when the fallback is off or fails)."""
        if self._browser is None:
            return []
        try:
            return await self._browser.jobs(http, url)
        except Challenge:
            raise Unsupported(CHALLENGE_MESSAGE) from None
        except BrowserError:
            return []

    async def _finish(self, http: Http, found: list[JobStub], company: str) -> list[JobStub]:
        """Listing entries with a description are done; the rest go through the normal per-job
        path (JSON-LD, labelled location, AI), keeping what the listing already told us."""
        done = [_with_company(s, company) for s in found if s.description]
        listed = {s.url: s for s in found if not s.description}
        for job in await self._jobs(http, list(listed), company):
            lst = listed.get(job.url)
            done.append(
                job
                if lst is None
                else job.model_copy(
                    update={
                        "title": lst.title,
                        "location": job.location or lst.location,
                        "posted_at": job.posted_at or lst.posted_at,
                        "ats": lst.ats or job.ats,
                    }
                )
            )
        return done

    async def _fetch(self, http: Http, url: str) -> str:
        if not await http.allowed(url):
            raise Unsupported(f"robots.txt does not allow fetching {url}")
        resp = await http.get(url)
        title = LexborHTMLParser(resp.text).css_first("title")
        if is_challenge(resp.status_code, title.text() if title else "", resp.text):
            raise Unsupported(CHALLENGE_MESSAGE)
        resp.raise_for_status()
        return resp.text

    async def _job_links(self, http: Http, url: str, html: str, limit: int) -> list[str]:
        links: dict[str, str] = {}
        seen = {normalize_url(url)}
        for page in range(MAX_LIST_PAGES):
            nxt = ""
            for a in LexborHTMLParser(html).css("a[href]"):
                href = urljoin(url, (a.attributes.get("href") or "").strip()).split("#")[0]
                if not href.startswith("http") or site(href) != site(url):
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

    async def _page(
        self, http: Http, url: str, company: str
    ) -> JobStub | tuple[str, str, str, str] | None:
        """A finished stub, or (url, h1/title, text, location) for a page that needs the AI."""
        if not await http.allowed(url):
            return None
        try:
            html = await self._fetch(http, url)
        except (httpx.HTTPError, RetryableStatus):  # a dead link must not sink the page
            return None
        if postings := job_postings(html):
            return _with_company(to_stub(postings[0], self.name, url, None), company)
        tree = LexborHTMLParser(html)
        h1, location = tree.css_first("h1"), _location(tree)
        title, text = _title(tree), _main_text(html)
        if h1 and h1.text().strip() and location:  # title + location: no AI needed
            return self._stub(url, company, title, text, None, location)
        return url, title, text, location

    def _stub(
        self,
        url: str,
        company: str,
        title: str,
        text: str,
        found: ExtractedJob | None,
        location: str = "",
    ) -> JobStub:
        location = (found.location if found else "") or location
        posted = None
        if found and found.posted_date:
            try:
                posted = from_iso(found.posted_date)
            except ValueError:
                posted = None
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

    async def _jobs(self, http: Http, links: list[str], company: str) -> list[JobStub]:
        done: list[JobStub] = []
        pending: list[tuple[str, str, str, str]] = []
        for link in links:
            page = await self._page(http, link, company)
            if isinstance(page, JobStub):
                done.append(page)
            elif page:
                pending.append(page)
        found = await self._extract([text for _, _, text, _ in pending])
        for n, (url, title, text, location) in enumerate(pending):
            done.append(self._stub(url, company, title, text, found.get(n), location))
        return done

    async def _extract(self, texts: list[str]) -> dict[int, ExtractedJob]:
        """One AI call for a batch of pages; ids are ours, any other id in the reply is dropped."""
        if self.provider is None or not texts:
            return {}
        pages = [{"id": n, "text": t[:EXCERPT]} for n, t in enumerate(texts)]
        try:
            result = await self.provider.complete(
                render("extract_job.j2", pages=pages), ExtractedBatch
            )
        except UsageLimitError:
            raise  # pause the run cleanly instead of silently degrading
        except ProviderError:
            return {}
        out: dict[int, ExtractedJob] = {}
        for job in result.jobs:
            if 0 <= job.id < len(texts):
                out.setdefault(job.id, job)
        return out
