"""Small helpers shared by source plugins."""

import asyncio
import html
import re
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Collection,
    Iterator,
    Mapping,
    Sequence,
)
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar
from urllib.parse import urljoin

import httpx

from linkit_all.sources.base import JobStub
from linkit_all.sources.careers import Unsupported
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.text import html_to_text

T = TypeVar("T")
# Failures that cost one posting, not the board: refused, an HTTP error, or 429/5xx after retries.
GONE = (Unsupported, httpx.HTTPError, RetryableStatus)
CHUNK = 20  # postings per page when their detail fetches run together (Http paces them per host)
PAGE = 25  # postings per yielded page when every posting costs one request (`paged_postings`)
XHR = {"X-Requested-With": "XMLHttpRequest"}  # what the sites' own scripts send with their calls
_LOC = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
_URL = re.compile(r"<url>(.*?)</url>", re.S | re.I)
_LASTMOD = re.compile(r"<lastmod>\s*([^<]+?)\s*</lastmod>", re.I)

strip_html = html_to_text  # (markup, escaped=False) -> plain text


def absolute(url: str | None, base: str) -> str:
    """`url` resolved against `base` ("//cdn/x", "/jobs/1", "jobs/1"); "" for a missing url."""
    return urljoin(base, url.strip()) if url and url.strip() else ""


def retry_after(resp: httpx.Response) -> float | None:
    """Seconds the server asks us to wait (Retry-After as seconds or HTTP date), else None."""
    value = resp.headers.get("Retry-After", "").strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, (when - datetime.now(UTC)).total_seconds()) if when.tzinfo else None


async def retry_while(
    call: Callable[[], Awaitable[httpx.Response]],
    attempts: int = 4,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    retry_on: Collection[int] = (403, 429),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> httpx.Response:
    """Call until the status is not in `retry_on`, at most `attempts` times, waiting
    base_delay * 2**n (capped at max_delay) between tries, or the server's Retry-After when it
    sends one. If Retry-After is longer than max_delay we stop and return that response:
    waiting less than asked is not polite. The last response is returned either way, so the
    caller decides what a final 403/429 means. (`Http` already retries 429/5xx itself; this is
    for sites that answer 403 or need other limits.)"""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    for n in range(attempts):
        resp = await call()
        if resp.status_code not in retry_on or n == attempts - 1:
            return resp
        wait = retry_after(resp)
        if wait is None:
            wait = min(max_delay, base_delay * 2**n)
        elif wait > max_delay:
            return resp
        await sleep(wait)
    raise AssertionError("unreachable")  # pragma: no cover


async def paged(
    fetch: Callable[[int], Awaitable[tuple[list[T], int | None]]],
    page_size: int,
    start_page: int = 0,
    max_pages: int = 1000,
) -> AsyncIterator[list[T]]:
    """Offset paging: `fetch(offset)` returns (items, total or None); yields one list per page.
    Stops on an empty or short page, once `total` is reached, or after `max_pages`. Starting at
    `start_page` resumes a checkpointed run. Use as `async for items in paged(...)` inside
    `search()` and turn each list into stubs."""
    offset = start_page * page_size
    for _ in range(max_pages):
        items, total = await fetch(offset)
        if not items:
            return
        yield items
        offset += len(items)
        if len(items) < page_size or (total is not None and offset >= total):
            return


async def get_page(http: Http, url: str) -> httpx.Response:
    """GET a human-facing page (the host's Crawl-delay applies). HTTP errors raise (the runner
    records them); nothing is retried around a block."""
    await http.allowed(url)
    resp = await http.get(url)
    resp.raise_for_status()
    return resp


async def fetch_html(http: Http, url: str) -> str | None:
    """The page text; None when the site says the page is gone (404/410)."""
    await http.allowed(url)
    resp = await http.get(url)
    if resp.status_code in (404, 410):
        return None
    resp.raise_for_status()
    return resp.text


async def page_text(http: Http, url: str) -> str | None:
    """GET of one detail page; None when it is gone, refused or unreadable, so
    one bad posting never stops the board."""
    try:
        return (await get_page(http, url)).text
    except GONE:
        return None


async def fetch_all(http: Http, urls: list[str], parse: Callable[[str, str], T | None]) -> list[T]:
    """GET every page together (Http paces them per host) and map `parse(html, url)` over the
    ones that exist and parse; a page that is gone (404/410) or parses to None is left out."""

    async def one(url: str) -> T | None:
        try:
            resp = await get_page(http, url)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 410):
                return None
            raise
        return parse(resp.text, url)

    return [r for r in await asyncio.gather(*(one(u) for u in urls)) if r is not None]


async def post_form(
    http: Http, url: str, data: Mapping[str, Any], headers: Mapping[str, str] | None = None
) -> httpx.Response:
    """`Http.post_form`, with HTTP errors raised."""
    resp = await http.post_form(url, data, headers)
    resp.raise_for_status()
    return resp


async def json_or_none(http: Http, url: str, **kwargs: Any) -> Any:
    """GET JSON; None when the posting is gone (404/410). Other HTTP errors raise."""
    resp = await http.get(url, **kwargs)
    if resp.status_code in (404, 410):
        return None
    resp.raise_for_status()
    return resp.json()


def chunks(items: Sequence[T], start_page: int, size: int = CHUNK) -> Iterator[Sequence[T]]:
    """`items` in pages of `size`, from page `start_page` (a checkpointed run resumes there)."""
    for i in range(start_page * size, len(items), size):
        yield items[i : i + size]


async def hydrate(
    items: Sequence[T],
    start_page: int,
    build: Callable[[T], Awaitable[JobStub | None]],
    size: int,
) -> AsyncIterator[list[JobStub]]:
    """Walk `items` `size` at a time from page `start_page`; each page's postings are built
    together (Http paces them per host) and the ones `build` returns None for are left out."""
    for i in range(start_page * size, len(items), size):
        built = await asyncio.gather(*(build(item) for item in items[i : i + size]))
        yield [s for s in built if s is not None]


async def paged_postings(
    items: list[str], start_page: int, build: Callable[[str], Awaitable[JobStub | None]]
) -> AsyncIterator[list[JobStub]]:
    """Walk `items` PAGE at a time, yielding what `build` returns for each (None = skip), so a
    long sitemap checkpoints and resumes."""
    for i in range(start_page * PAGE, len(items), PAGE):
        yield [s for item in items[i : i + PAGE] if (s := await build(item))]


async def posting_pages(
    urls: list[str],
    start_page: int,
    limit: int,
    build: Callable[[str], Awaitable[JobStub | None]],
) -> AsyncIterator[list[JobStub]]:
    """Build a stub from each of the first `limit` URLs, CHUNK at a time (one page per chunk).
    Empty pages are yielded too, so the checkpoint's page number stays the chunk number."""
    async for page in hydrate(urls[:limit], start_page, build, CHUNK):
        yield page


def sitemap_locs(xml: str) -> list[str]:
    """Every <loc> of a sitemap, in order, unescaped."""
    return [u.replace("&amp;", "&") for u in _LOC.findall(xml)]


async def sitemap_text(http: Http, url: str) -> str:
    """A sitemap's text; HTTP errors raise."""
    return (await get_page(http, url)).text


async def sitemap_pages(http: Http, url: str) -> list[str]:
    """Every page URL of a sitemap or of the sitemaps an index lists (one level down). A
    sub-sitemap that fails to load is left out."""
    locs = sitemap_locs((await get_page(http, url)).text)
    urls: list[str] = []
    for loc in locs:
        if not loc.endswith(".xml"):
            urls.append(loc)
            continue
        try:
            urls += [u for u in sitemap_locs((await get_page(http, loc)).text)]
        except (httpx.HTTPError, RetryableStatus):
            continue
    return urls


async def child_sitemap_urls(
    http: Http, index_url: str, needle: str, keep: Callable[[str], bool]
) -> list[str]:
    """Posting URLs of the sub-sitemap of `index_url` whose address contains `needle`, in sitemap
    order, de-duplicated, keeping those `keep` accepts."""
    child = next(
        (u for u in sitemap_locs((await get_page(http, index_url)).text) if needle in u), ""
    )
    if not child:
        raise ValueError(f"{index_url} lists no {needle!r} sitemap")
    urls = sitemap_locs((await get_page(http, child)).text)
    return list(dict.fromkeys(u for u in urls if keep(u)))


def sitemap_by_date(xml: str, keep: Callable[[str], bool]) -> list[str]:
    """The `<loc>`s of a urlset that pass `keep`, newest `<lastmod>` first, without repeats."""
    rows = []
    for block in _URL.findall(xml):
        loc, mod = _LOC.search(block), _LASTMOD.search(block)
        if loc and keep(url := html.unescape(loc[1])):
            rows.append((mod[1] if mod else "", url))
    rows.sort(key=lambda r: r[0], reverse=True)  # stable: sitemap order among equal dates
    return list(dict.fromkeys(url for _, url in rows))
