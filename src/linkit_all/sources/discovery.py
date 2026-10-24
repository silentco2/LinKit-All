"""Company boards found in Common Crawl's URL index, kept in the `boards` table.

`discover_boards` asks the CDX index which URLs on an ATS's hosts (`Source.cdx_hosts`) were
crawled, turns them into board slugs with the plugin's own `url_patterns`, and stores them.
`board_tasks` then hands the oldest-crawled ones to the discover stage, a few hundred per run,
and `note_crawl` records how each went (boards that fail 5 times in a row are switched off).
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Collection
from dataclasses import dataclass
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from linkit_all.core.models import Board, utcnow
from linkit_all.core.search import SearchConfig
from linkit_all.sources.ats_detector import detect
from linkit_all.sources.base import Source, Task
from linkit_all.sources.common import retry_while
from linkit_all.sources.http import Http, RetryableStatus

COLLINFO = "https://index.commoncrawl.org/collinfo.json"
CC_HOST = "index.commoncrawl.org"
CC_RATE = 1.0  # requests per second to the index
MAX_FAILURES = 5  # failed crawls in a row before a board is switched off
# Path segments that look like a slug but are the vendor's own pages or crawler leftovers.
NOT_SLUGS = frozenset(
    {"robots", "sitemap", "favicon", "static", "assets", "images", "image", "api", "wday", "en"}
    | {"embed", "www", "careers", "help", "support", "blog", "login", "signup"}
)


class DiscoveryError(Exception):
    """Common Crawl could not be used (robots.txt, network, unexpected answer)."""


@dataclass
class AtsResult:
    found: int = 0  # distinct boards seen in the index (capped)
    new: int = 0  # of those, not in the table before
    error: str = ""


def make_http(client: httpx.AsyncClient) -> Http:
    """An `Http` that sends the index at most `CC_RATE` requests per second."""
    return Http(client, per_host_rate={CC_HOST: CC_RATE})


async def _get(
    http: Http,
    url: str,
    sleep: Callable[[float], Awaitable[None]],
    **kwargs: Any,
) -> httpx.Response:
    try:
        return await retry_while(lambda: http.get(url, **kwargs), sleep=sleep)
    except (httpx.HTTPError, RetryableStatus) as e:  # RetryableStatus: 429/5xx after retries
        raise DiscoveryError(f"{url}: {e}") from e


async def latest_index(http: Http, sleep: Callable[[float], Awaitable[None]]) -> str:
    """CDX API root of the newest collection, after checking the index's robots.txt."""
    if not await http.allowed(COLLINFO):
        raise DiscoveryError(f"{CC_HOST} robots.txt does not allow {COLLINFO}")
    resp = await _get(http, COLLINFO, sleep)
    try:
        resp.raise_for_status()
        index = f"https://{CC_HOST}/{resp.json()[0]['id']}-index"
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as e:
        raise DiscoveryError(f"unexpected answer from {COLLINFO}: {e}") from e
    if not await http.allowed(index):
        raise DiscoveryError(f"{CC_HOST} robots.txt does not allow queries to {index}")
    return index


async def cdx_urls(
    http: Http, index: str, pattern: str, sleep: Callable[[float], Awaitable[None]]
) -> AsyncIterator[str]:
    """Every crawled URL (status 200) matching `pattern`, page by page."""
    query = {"url": pattern, "output": "json", "fl": "url", "filter": "status:200"}
    resp = await _get(http, index, sleep, params={**query, "showNumPages": "true"})
    if resp.status_code == 404:  # "No Captures found"
        return
    try:
        resp.raise_for_status()
        pages = int(resp.json().get("pages", 0))
    except (httpx.HTTPError, ValueError, AttributeError) as e:
        raise DiscoveryError(f"page count for {pattern}: {e}") from e
    for page in range(pages):
        resp = await _get(http, index, sleep, params={**query, "page": page})
        try:
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise DiscoveryError(f"{pattern} page {page}: {e}") from e
        for line in resp.text.splitlines():
            try:
                yield str(json.loads(line)["url"])
            except (ValueError, KeyError, TypeError):  # a cut-off or odd line: skip it
                continue


def slug_of(url: str, src: Source) -> str | None:
    """The board slug `src` reads out of a crawled URL, or None if it is not a board."""
    found = detect(url, [src])
    if found is None or found[0] != src.name:
        return None
    slug = found[1]
    return None if slug.rsplit("/", 1)[-1].lower() in NOT_SLUGS else slug


async def discover_ats(
    http: Http,
    index: str,
    src: Source,
    cap: int,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[str]:
    """Distinct board slugs (case-insensitive) for one ATS, at most `cap`. A failure partway
    keeps what was found: the error is raised only when nothing came back."""
    seen: dict[str, str] = {}
    try:
        for pattern in src.cdx_hosts:
            async for url in cdx_urls(http, index, pattern, sleep):
                if (slug := slug_of(url, src)) and slug.lower() not in seen:
                    seen[slug.lower()] = slug
                    if len(seen) >= cap:
                        return list(seen.values())
    except DiscoveryError:
        if not seen:
            raise
        logger.warning("{}: index stopped early after {} boards", src.name, len(seen))
    return list(seen.values())


def upsert_boards(db: sessionmaker[Session], ats: str, slugs: Collection[str], source: str) -> int:
    """Insert the boards not stored yet (slugs compared case-insensitively); returns how many."""
    with db.begin() as s:
        have = {slug.lower() for slug in s.scalars(select(Board.slug).filter_by(ats=ats))}
        new = []
        for slug in slugs:
            if slug.lower() not in have:
                have.add(slug.lower())
                new.append(Board(ats=ats, slug=slug, source=source))
        s.add_all(new)
    return len(new)


async def discover_boards(
    db: sessionmaker[Session],
    http: Http,
    registry: dict[str, Source],
    ats: Collection[str] = (),
    max_per_ats: int = 5000,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> dict[str, AtsResult]:
    """Fill the `boards` table from Common Crawl for `ats` (default: every ATS plugin that
    declares `cdx_hosts`). Raises DiscoveryError when the index cannot be used at all, and
    ValueError for an ATS name that has no `cdx_hosts`."""
    ready = {n: s for n, s in registry.items() if s.kind == "ats" and s.cdx_hosts}
    if bad := [n for n in ats if n not in ready]:
        raise ValueError(f"cannot discover boards for: {', '.join(bad)} (try {', '.join(ready)})")
    index = await latest_index(http, sleep)
    out: dict[str, AtsResult] = {}
    for name in ats or ready:
        result = out[name] = AtsResult()
        try:
            slugs = await discover_ats(http, index, ready[name], max_per_ats, sleep)
        except DiscoveryError as e:
            result.error = str(e)
            logger.warning("{}: {}", name, e)
            continue
        result.found = len(slugs)
        result.new = upsert_boards(db, name, slugs, "commoncrawl")
    return out


def board_tasks(
    db: sessionmaker[Session], cfg: SearchConfig, registry: dict[str, Source], skip: Collection[str]
) -> list[Task]:
    """Tasks for the active stored boards crawled longest ago (never-crawled first), at most
    `boards_per_run`. Keys in `skip` (the user's own companies) are left out."""
    n = cfg.sources.boards_per_run
    if not cfg.sources.use_discovered_boards or n == 0:
        return []
    with db() as s:
        rows = s.execute(
            select(Board.ats, Board.slug)
            .where(Board.active, Board.ats.in_([k for k, v in registry.items() if v.kind == "ats"]))
            .order_by(Board.last_crawled_at.asc().nulls_first(), Board.id)
            .limit(n + len(skip))
        ).all()
    tasks = [Task(ats, f"{ats}:{slug}", board=slug) for ats, slug in rows]
    return [t for t in tasks if t.key not in skip][:n]


def note_crawl(db: sessionmaker[Session], ats: str, slug: str, jobs: int, ok: bool) -> None:
    """Record one crawl of a stored board: jobs seen, and the failure streak."""
    with db.begin() as s:
        board = s.scalar(select(Board).filter_by(ats=ats, slug=slug))
        if board is None:  # a board that is not stored (a user's own company)
            return
        board.last_crawled_at = utcnow()
        board.last_jobs = jobs if ok else board.last_jobs
        board.failures = 0 if ok else board.failures + 1
        if board.failures >= MAX_FAILURES:
            board.active = False
