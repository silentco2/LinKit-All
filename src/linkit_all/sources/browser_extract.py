"""Careers pages that draw their jobs with JavaScript: read them in Chrome, let the AI pick *how*.

The page is opened once, headless (never past a bot challenge), and three kinds of evidence are
collected: JSON-LD JobPostings, JSON the page loaded in the background, and a summary of the
rendered DOM's repeated blocks. One AI call per site (cached per host in recipes.json) chooses
`json_ld`, `api_response` or `css` plus its parameters. The model only decides: our code checks
the recipe against what we captured and runs it, and every job URL comes from the page or from a
captured response, never from the model.
"""

import asyncio
import contextlib
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit

from playwright.async_api import (
    Browser,
    Page,
    Playwright,
    Request,
    Route,
    async_playwright,
)
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeout
from pydantic import BaseModel, ValidationError
from selectolax.lexbor import LexborHTMLParser, LexborNode

from linkit_all.providers.base import LLMProvider, ProviderError, UsageLimitError, render
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, from_iso, remote_from_text
from linkit_all.sources.http import Http
from linkit_all.sources.jsonld import job_postings, to_stub
from linkit_all.sources.text import html_to_text, normalize_url

SOURCE = "careers"
NAV_TIMEOUT_MS = 20_000  # wait for network idle at most this long, then use what has loaded
MAX_PAGES = 2  # pages open at once, over all hosts (one per host)
MAX_JSON = 2_000_000  # bytes of a background JSON response we keep
MAX_RESPONSES = 12
MAX_KEYS = 12
MAX_SHAPE_LINES = 10
MIN_REPEAT = 3  # fewer repeats is not a list of jobs
MAX_GROUPS = 6
SAMPLE = 120  # characters of a sample's text shown to the model
METHODS: tuple[str, ...] = ("json_ld", "api_response", "css")

CHALLENGE = re.compile(
    r"just a moment|attention required|verify you are human|are you a robot|captcha|cf-chl", re.I
)
_SECOND_LEVEL = {"co", "com", "org", "gov", "ac", "net"}
_JOB_API = re.compile(
    r"/(?:jobs?|positions?|vacanc(?:y|ies)|openings?|postings?|requisitions?)\b", re.I
)
_CLASS = re.compile(r"^[A-Za-z_][\w-]*$")
_SKIP_TAGS = {"option", "br", "path", "meta", "link", "hr", "source"}


class BrowserError(Exception):
    """The browser route is not available for this page (no Chrome, load failure)."""


class Challenge(BrowserError):
    """The page answered with a bot challenge. We stop; we never try to pass it."""


def site(url: str) -> str:
    """Registrable domain, good enough without a public-suffix list (example.co.uk)."""
    parts = (urlsplit(url).hostname or "").split(".")
    keep = 3 if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in _SECOND_LEVEL else 2
    return ".".join(parts[-keep:])


def is_challenge(status: int, title: str, text: str) -> bool:
    return bool(CHALLENGE.search(title) or (status >= 400 and CHALLENGE.search(text[:5000])))


# --- what the page showed us -------------------------------------------------------------


@dataclass
class Capture:
    url: str
    html: str  # the rendered DOM
    json_ld: list[dict[str, Any]] = field(default_factory=list)
    responses: dict[str, Any] = field(default_factory=dict)  # url -> parsed background JSON


def _brief(item: Any) -> str:
    """`{id=12, title=Backend Eng, location}`: an item's keys with a short sample of scalars."""
    if not isinstance(item, dict):
        return type(item).__name__
    parts = [
        f"{str(k)[:30]}={' '.join(str(v).split())[:30]}"
        if isinstance(v, str | int | float) and not isinstance(v, bool)
        else str(k)[:30]
        for k, v in list(item.items())[:MAX_KEYS]
    ]
    return "{" + ", ".join(parts) + ("..." if len(item) > MAX_KEYS else "") + "}"


def shape(data: Any, path: str = "", depth: int = 4) -> list[str]:
    """Compact outline of a JSON document: objects with their keys, arrays with their length and
    their first item's keys. Paths are dotted and can be used as `items_path` as they are."""
    here = path or "$"
    if isinstance(data, list):
        return [f"{here}: array[{len(data)}] of {_brief(data[0]) if data else 'nothing'}"]
    if not isinstance(data, dict):
        return []
    lines = [f"{here}: object {_brief(data)}"]
    if depth:
        for key, value in list(data.items())[:MAX_KEYS]:
            if isinstance(value, dict | list):
                lines += shape(value, f"{path}.{key}" if path else str(key), depth - 1)
    return lines[:MAX_SHAPE_LINES]


def _css_part(node: LexborNode) -> str:
    classes = [c for c in (node.attributes.get("class") or "").split() if _CLASS.match(c)]
    return (node.tag or "") + "".join(f".{c}" for c in classes[:2])


def _path(node: LexborNode) -> str:
    parts: list[str] = []
    cur: LexborNode | None = node
    while cur is not None and cur.tag not in ("body", "html", "-undef", None) and len(parts) < 3:
        parts.append(_css_part(cur))
        cur = cur.parent
    return " > ".join(reversed(parts))


def dom_groups(html: str, page_url: str) -> list[dict[str, Any]]:
    """The most repeated sibling groups of the rendered page: CSS selector, count, 2 samples."""
    tree = LexborHTMLParser(html)
    tree.strip_tags(["script", "style", "svg", "noscript", "template"])
    groups: list[dict[str, Any]] = []
    for parent in tree.css("body, body *"):
        buckets: dict[str, list[LexborNode]] = {}
        for child in parent.iter():
            if child.tag and child.tag not in _SKIP_TAGS:
                buckets.setdefault(_css_part(child), []).append(child)
        for part, members in buckets.items():
            if len(members) < MIN_REPEAT:
                continue
            samples = []
            for m in members[:2]:
                a = m if m.tag == "a" and m.attributes.get("href") else m.css_first("a[href]")
                href = urljoin(page_url, a.attributes.get("href") or "") if a else ""
                samples.append(
                    {"text": " ".join(m.text(separator=" ").split())[:SAMPLE], "href": href}
                )
            if not any(s["text"] for s in samples):
                continue
            prefix = _path(parent) if parent.tag != "body" else "body"
            groups.append(
                {
                    "selector": f"{prefix} > {part}",
                    "count": len(members),
                    "samples": samples,
                    "links": any(s["href"] for s in samples),
                }
            )
    groups.sort(key=lambda g: (g["links"], g["count"]), reverse=True)
    return groups[:MAX_GROUPS]


def evidence(cap: Capture) -> dict[str, Any]:
    """Everything the model is shown. Truncated on purpose; no scripts, no styles."""
    return {
        "url": cap.url,
        "json_ld": [" ".join(str(p.get("title", "")).split())[:SAMPLE] for p in cap.json_ld[:3]],
        "json_ld_count": len(cap.json_ld),
        "responses": [{"url": u, "shape": shape(d)} for u, d in list(cap.responses.items())[:6]],
        "groups": dom_groups(cap.html, cap.url),
    }


# --- the model's recipe and our execution of it --------------------------------------------


class Fields(BaseModel):
    title: str
    url: str
    location: str | None = None
    posted: str | None = None
    description: str | None = None


class CssRecipe(BaseModel):
    item: str
    title: str
    link: str
    location: str | None = None
    posted: str | None = None


class Recipe(BaseModel):
    method: Literal["json_ld", "api_response", "css"]
    api_url: str | None = None
    items_path: str | None = None
    fields: Fields | None = None
    css: CssRecipe | None = None
    reason: str = ""


def _get(item: Any, path: str | None) -> str:
    """A dotted path inside one item, as text. Lists of scalars are joined, anything else is ''."""
    cur = item
    for part in (path or "").split("."):
        if not part:
            return ""
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return ""
    if isinstance(cur, list):
        cur = ", ".join(str(x) for x in cur if isinstance(x, str | int | float))
    return " ".join(str(cur).split()) if isinstance(cur, str | int | float) else ""


def _accept(href: str, page_url: str) -> tuple[str, str | None] | None:
    """(absolute url, ats) when the link is on the page's own site or a known ATS, else None."""
    url = urljoin(page_url, href.strip()).split("#")[0]
    if not url.startswith(("http://", "https://")):
        return None
    found = detect(url)
    if site(url) != site(page_url) and found is None:
        return None
    return url, found[0] if found else None


def _stub(
    page_url: str, title: str, href: str, location: str, posted: str, description: str
) -> JobStub | None:
    accepted = _accept(href, page_url) if href else None
    title = " ".join(title.split())
    if not title or accepted is None:
        return None
    try:
        posted_at = from_iso(posted) if posted else None
    except ValueError:
        posted_at = None
    return JobStub(
        source=SOURCE,
        url=accepted[0],
        title=title,
        company="Unknown",
        location=location,
        description=html_to_text(description) if description else "",
        posted_at=posted_at,
        ats=accepted[1],
        apply_url=accepted[0],
        remote=remote_from_text(title, location),
    )


def _unique(stubs: list[JobStub | None]) -> list[JobStub]:
    seen: dict[str, JobStub] = {}
    for s in stubs:
        if s is not None:
            seen.setdefault(normalize_url(s.url), s)
    return list(seen.values())


def _from_json_ld(recipe: Recipe, cap: Capture) -> list[JobStub]:
    stubs = [to_stub(p, SOURCE, p.get("url") or cap.url, None) for p in cap.json_ld]
    return [s for s in stubs if s.title]


def _from_api(recipe: Recipe, cap: Capture) -> list[JobStub]:
    if not recipe.api_url or recipe.api_url not in cap.responses or recipe.fields is None:
        return []  # a URL the model made up is not one of our captures: nothing to run
    data: Any = cap.responses[recipe.api_url]
    path = (recipe.items_path or "").removeprefix("$").strip(".")
    for part in filter(None, path.split(".")):
        if isinstance(data, dict):
            data = data.get(part)
        elif isinstance(data, list) and part.isdigit() and int(part) < len(data):
            data = data[int(part)]
        else:
            return []
    if not isinstance(data, list):
        return []
    f = recipe.fields
    return _unique(
        [
            _stub(
                cap.url,
                _get(item, f.title),
                _get(item, f.url),
                _get(item, f.location),
                _get(item, f.posted),
                _get(item, f.description),
            )
            for item in data
            if isinstance(item, dict)
        ]
    )


def _pick(node: LexborNode, selector: str | None) -> LexborNode | None:
    if not selector or selector in (":scope", "&"):
        return node
    return node.css_first(selector)


def _from_css(recipe: Recipe, cap: Capture) -> list[JobStub]:
    c = recipe.css
    if c is None:
        return []
    out: list[JobStub | None] = []
    try:  # selectors are the model's; a bad one is just "no jobs"
        for node in LexborHTMLParser(cap.html).css(c.item):
            title, link = _pick(node, c.title), _pick(node, c.link)
            if link is not None and not link.attributes.get("href"):
                link = link.css_first("a[href]")
            where = _pick(node, c.location) if c.location else None
            when = _pick(node, c.posted) if c.posted else None
            posted = (when.attributes.get("datetime") or when.text()) if when else ""
            out.append(
                _stub(
                    cap.url,
                    title.text() if title else "",
                    (link.attributes.get("href") or "") if link else "",
                    " ".join(where.text().split()) if where else "",
                    posted.strip(),
                    "",
                )
            )
    except Exception:
        return []
    return _unique(out)


_RUN: dict[str, Callable[[Recipe, Capture], list[JobStub]]] = {
    "json_ld": _from_json_ld,
    "api_response": _from_api,
    "css": _from_css,
}


def run_recipe(recipe: Recipe, cap: Capture) -> tuple[list[JobStub], str]:
    """Jobs from the recipe's method; if that yields none, from the next method that has the
    evidence and (for api/css) the parameters, in order json_ld -> api_response -> css."""
    for method in [recipe.method, *(m for m in METHODS if m != recipe.method)]:
        if jobs := _RUN[method](recipe, cap):
            return jobs, method
    return [], ""


class RecipeCache:
    """`recipes.json`: the working recipe per host. Parameters only, never page contents."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _read(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, host: str) -> Recipe | None:
        try:
            return Recipe.model_validate(self._read().get(host))
        except ValidationError:
            return None

    def put(self, host: str, recipe: Recipe) -> None:
        data = self._read()
        data[host] = {
            **recipe.model_dump(exclude_none=True, exclude={"reason"}),
            "saved_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self._write(data)

    def drop(self, host: str) -> None:
        data = self._read()
        if data.pop(host, None) is not None:
            self._write(data)

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), "utf-8")


# --- the browser ---------------------------------------------------------------------------


class PageBrowser:
    """One shared headless Chrome, started on the first page. At most MAX_PAGES pages at once
    and one per host. `route` lets tests answer every request without a network."""

    def __init__(self, route: Callable[[Route, Request], Awaitable[None]] | None = None) -> None:
        self._route = route
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._start = asyncio.Lock()
        self._slots = asyncio.Semaphore(MAX_PAGES)
        self._hosts: dict[str, asyncio.Lock] = {}

    async def _chrome(self) -> Browser:
        async with self._start:
            if self._browser is None:
                try:
                    self._pw = await async_playwright().start()
                    self._browser = await self._pw.chromium.launch(channel="chrome", headless=True)
                except PlaywrightError as e:
                    await self.close()
                    raise BrowserError(f"Chrome could not be started: {e}") from None
            return self._browser

    async def close(self) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._pw is not None:
            await self._pw.stop()
        self._browser = self._pw = None
        self._hosts.clear()

    async def capture(self, http: Http, url: str) -> Capture:
        await http.allowed(url)  # picks up the host's Crawl-delay before every navigation
        parts = urlsplit(url)
        host_lock = self._hosts.setdefault(parts.netloc.lower(), asyncio.Lock())
        async with host_lock, self._slots:
            browser = await self._chrome()
            await http._limiter(parts.hostname or "").acquire()  # the load is one request
            ctx = await browser.new_context()
            try:
                if self._route is not None:
                    await ctx.route("**/*", self._route)
                return await self._load(await ctx.new_page(), url)
            except PlaywrightError as e:
                raise BrowserError(f"the page could not be loaded: {e}") from None
            finally:
                await ctx.close()

    async def _load(self, page: Page, url: str) -> Capture:
        responses: dict[str, Any] = {}

        async def grab(resp: Any) -> None:
            if (
                len(responses) >= MAX_RESPONSES
                or resp.request.resource_type not in ("xhr", "fetch")
                or "json" not in resp.headers.get("content-type", "").lower()
                or not (site(resp.url) == site(url) or _JOB_API.search(urlsplit(resp.url).path))
            ):
                return
            body = await resp.body()
            if len(body) <= MAX_JSON:
                with contextlib.suppress(ValueError):
                    responses[resp.url] = json.loads(body)

        grabs: list[asyncio.Future[None]] = []
        page.on("response", lambda r: grabs.append(asyncio.ensure_future(grab(r))))
        status = 0
        try:
            resp = await page.goto(url, wait_until="networkidle", timeout=NAV_TIMEOUT_MS)
            status = resp.status if resp else 0
        except PlaywrightTimeout:
            pass  # busy page: use what has loaded
        await asyncio.gather(*grabs, return_exceptions=True)
        html, title = await page.content(), await page.title()
        if is_challenge(status, title, html):
            raise Challenge("the site answered with a bot challenge; it is not bypassed")
        return Capture(url, html, job_postings(html), responses)


class BrowserExtractor:
    """Capture -> (cached or AI-chosen) recipe -> jobs."""

    def __init__(
        self,
        provider: LLMProvider,
        folder: Path,
        route: Callable[[Route, Request], Awaitable[None]] | None = None,
    ) -> None:
        self.provider = provider
        self.browser = PageBrowser(route)
        self.cache = RecipeCache(folder / "recipes.json")

    async def close(self) -> None:
        await self.browser.close()

    async def jobs(self, http: Http, url: str) -> list[JobStub]:
        """Stubs read from the rendered page ([] when nothing worked). Raises BrowserError
        (Challenge included) and UsageLimitError; other provider errors give []."""
        cap = await self.browser.capture(http, url)
        host = urlsplit(url).netloc.lower()
        if (cached := self.cache.get(host)) is not None:
            jobs, method = run_recipe(cached, cap)
            if jobs:
                self.cache.put(host, cached.model_copy(update={"method": method}))
                return jobs
            self.cache.drop(host)  # stale: the page changed; ask once more
        try:
            recipe = await self.provider.complete(
                render("extract_recipe.j2", **evidence(cap)), Recipe
            )
        except UsageLimitError:
            raise  # pause the run cleanly
        except ProviderError:
            return []
        jobs, method = run_recipe(recipe, cap)
        if jobs:
            self.cache.put(host, recipe.model_copy(update={"method": method}))
        return jobs
