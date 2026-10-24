"""Small helpers shared by source plugins."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import TypeVar
from urllib.parse import urljoin

import httpx

from linkit_all.sources.text import html_to_text

T = TypeVar("T")

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
