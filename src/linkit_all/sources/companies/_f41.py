"""Helpers private to the F4.1 company plugins (the underscore keeps it out of the registry)."""

from collections.abc import AsyncIterator, Iterable
from typing import Any, TypeVar

import httpx

from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats._f13 import get_page, sitemap_locs
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import JobStub, Remote, Task, remote_from_text
from linkit_all.sources.http import Http, RetryableStatus

T = TypeVar("T")


def query_tasks(name: str, cfg: SearchConfig) -> list[Task]:
    """One task per search query, for a company API that searches; one unfiltered task (the
    newest postings) when no query is set."""
    s = cfg.search
    return [
        Task(name, f"{name}:{q}", query=q, limit=s.max_results_per_query,
             posted_within_days=s.posted_within_days)
        for q in s.queries or [""]
    ]  # fmt: skip


async def limited(pages: AsyncIterator[list[T]], limit: int) -> AsyncIterator[list[T]]:
    """`pages` cut off after `limit` items in all."""
    left = limit
    async for page in pages:
        if left <= 0:
            return
        yield page[:left]
        left -= len(page)


def ats_of(url: str | None, default: str) -> str:
    """The ATS a job's apply link points at, else `default` (the company's own site)."""
    found = detect(url) if url else None
    return found[0] if found else default


def remote_ru(*texts: str | None) -> Remote | None:
    """`remote_from_text` that also reads the Russian words (удалённо, гибрид)."""
    joined = " ".join(t for t in texts if t).lower()
    if "гибрид" in joined:
        return "hybrid"
    return "remote" if "удал" in joined else remote_from_text(joined)


async def sitemap_urls(http: Http, url: str) -> list[str]:
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


def first(data: dict[str, Any], *keys: str) -> str:
    """The first non-empty string among `keys` of `data`, else ""."""
    return next((str(data[k]) for k in keys if data.get(k)), "")


def fresh(stubs: Iterable[JobStub | None], seen: set[str]) -> list[JobStub]:
    """The stubs whose `extra["id"]` is not yet in `seen` (added to it), in order; skips None."""
    out: list[JobStub] = []
    for s in stubs:
        if s and s.extra["id"] not in seen:
            seen.add(s.extra["id"])
            out.append(s)
    return out
