"""Workday career sites via the public "cxs" JSON endpoint behind every myworkdayjobs.com page.

Board slug is "tenant/wdN/site", e.g. "nvidia/wd5/NVIDIAExternalCareerSite", or, for the host
Workday shares between tenants, "wdN.myworkdaysite.com/tenant/site".

The list endpoint stops at 2,000 jobs: a board that big reports exactly that as its `total`, and
past it the tenant silently loops back to page 1. Such boards are split by one of the facets the
response offers (a job family, a country, ...) until every slice fits, or the board fails loudly.
"""

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from linkit_all.sources.base import JobStub, Source, Task, remote_from_text
from linkit_all.sources.common import retry_while
from linkit_all.sources.http import Http, RetryableStatus
from linkit_all.sources.text import html_to_text

PAGE = 20  # the largest page size Workday's list endpoint accepts
CAP = 2000  # the `total` a capped board reports
MAX_DEPTH = 3  # facet dimensions combined when a slice is still capped
RETRIES = 6  # extra tries after a 403/429: 1 s doubling to 30 s, or the server's Retry-After
_LOCALE = r"(?:[a-z]{2}-[A-Z]{2}/)?"
# The enrich stage only hands us the stored URL, so ids are recovered from it.
_URL = re.compile(rf"https://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/{_LOCALE}([\w-]+)(/job/\S+)")
_SHARED_URL = re.compile(
    rf"https://(wd\d+\.myworkdaysite\.com)/{_LOCALE}recruiting/([\w-]+)/([\w-]+)(/job/\S+)"
)
_AGO = re.compile(r"(\d+)\+?\s+days?\s+ago", re.I)


class WorkdayCapped(RuntimeError):
    """A board over the 2,000 cap that facets cannot split: no silent partial list."""


async def _nap(seconds: float) -> None:  # looked up at call time so tests can patch it
    await asyncio.sleep(seconds)


def _board(slug: str) -> tuple[str, str, str, str]:
    """(host, tenant, site, public path prefix) of a board slug."""
    a, b, c = slug.split("/")
    if "." in a:  # wd1.myworkdaysite.com/tenant/site
        return a, b, c, f"recruiting/{b}/{c}"
    return f"{a}.{b}.myworkdayjobs.com", a, c, c


async def _send(http: Http, method: str, url: str, **kwargs: Any) -> httpx.Response:
    """One request, retried while Workday answers 403 or 429 (some tenants throttle with 403)."""

    async def once() -> httpx.Response:
        try:
            return await http.request(method, url, **kwargs)
        except RetryableStatus as e:  # Http gave up on a 429; our longer backoff takes over
            if e.response.status_code != 429:
                raise
            return e.response

    resp = await retry_while(once, attempts=RETRIES + 1, sleep=_nap)
    if resp.status_code in (403, 429):
        raise RetryableStatus(resp)  # still throttled: a resume retries the board later
    resp.raise_for_status()
    return resp


def _pick_dimension(
    facets: list[dict[str, Any]] | None, used: frozenset[str]
) -> tuple[str, list[str]] | None:
    """The unused facet dimension whose largest single value is smallest: it leaves the least
    oversized remainder, so the recursion is most likely to clear the cap in one more level."""
    dims = {
        f["facetParameter"]: [v for v in f.get("values") or [] if v.get("id")]
        for f in facets or []
        if f.get("facetParameter") and f["facetParameter"] not in used
    }
    dims = {k: v for k, v in dims.items() if v}
    if not dims:
        return None
    best = min(dims, key=lambda k: max(v.get("count") or 0 for v in dims[k]))
    return best, [v["id"] for v in dims[best]]


def parse_posted(text: str | None, now: datetime | None = None) -> datetime | None:
    """ "Posted 3 Days Ago" -> naive UTC midnight of that day; None when unrecognised."""
    if not text:
        return None
    low = text.lower()
    days = 0 if "today" in low else 1 if "yesterday" in low else None
    if days is None and (m := _AGO.search(low)):
        days = int(m.group(1))  # "30+ days ago" -> 30, the best we know
    if days is None:
        return None
    today = (now or datetime.now(UTC)).replace(
        tzinfo=None, hour=0, minute=0, second=0, microsecond=0
    )
    return today - timedelta(days=days)


class Workday(Source):
    name = "workday"
    kind = "ats"
    url_patterns = (
        re.compile(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/wday/cxs/[\w-]+/([\w-]+)", re.I),
        re.compile(r"([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)"),
        re.compile(r"(wd\d+\.myworkdaysite\.com)/wday/cxs/([\w-]+)/([\w-]+)", re.I),
        re.compile(rf"(wd\d+\.myworkdaysite\.com)/{_LOCALE}recruiting/([\w-]+)/([\w-]+)"),
    )
    cdx_hosts = ("*.myworkdayjobs.com",)  # host glob only: the index 502s on a path glob
    parallel = 4  # public JSON API; Http paces per host

    async def search(self, http: Http, task: Task, start_page: int) -> AsyncIterator[list[JobStub]]:
        host, tenant, site, _ = _board(task.board)
        url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
        company = tenant.replace("-", " ").title()
        first = await self._list(http, url, {}, start_page * PAGE)
        seen: set[str] = set()
        if first.get("total") == CAP:
            # ponytail: a resume re-walks the split and skips the pages already stored
            skip = start_page
            postings = self._split(http, url, task.board, {}, first, frozenset(), 0, seen)
        else:
            skip = 0
            postings = self._walk(http, url, {}, first, start_page * PAGE, seen)
        n = 0
        async for page in postings:
            n += 1
            if n > skip:
                yield [self.stub(p, task.board, company) for p in page]

    @staticmethod
    async def _list(http: Http, url: str, facets: dict[str, Any], offset: int) -> dict[str, Any]:
        body = {"appliedFacets": facets, "limit": PAGE, "offset": offset, "searchText": ""}
        data: dict[str, Any] = (await _send(http, "POST", url, json=body)).json()
        return data

    async def _walk(
        self,
        http: Http,
        url: str,
        facets: dict[str, Any],
        page: dict[str, Any],
        offset: int,
        seen: set[str],
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Page one (possibly facet-scoped) query to its end, starting from a fetched page."""
        total = 0  # only the first page may report it (later ones say 0): latch the first non-zero
        while postings := page.get("jobPostings") or []:
            total = total or page.get("total") or 0
            fresh = [p for p in postings if p["externalPath"] not in seen]
            seen.update(p["externalPath"] for p in fresh)  # a posting can sit in several slices
            if fresh:
                yield fresh
            offset += len(postings)
            if len(postings) < PAGE or (total and offset >= total):
                return
            page = await self._list(http, url, facets, offset)

    async def _split(
        self,
        http: Http,
        url: str,
        board: str,
        facets: dict[str, Any],
        capped: dict[str, Any],
        used: frozenset[str],
        depth: int,
        seen: set[str],
    ) -> AsyncIterator[list[dict[str, Any]]]:
        """Walk a capped query one facet value at a time, recursing into slices still capped."""
        dim = _pick_dimension(capped.get("facets"), used)
        if dim is None or depth >= MAX_DEPTH:
            why = (
                "no facet dimension left to split on"
                if dim is None
                else f"still capped after splitting {MAX_DEPTH} facet dimensions deep"
            )
            raise WorkdayCapped(f"workday {board} has {CAP}+ jobs and {why}")
        name, ids = dim
        for value in ids:
            scoped = {**facets, name: [value]}
            page = await self._list(http, url, scoped, 0)
            if page.get("total") == CAP:
                sub = self._split(http, url, board, scoped, page, used | {name}, depth + 1, seen)
            else:
                sub = self._walk(http, url, scoped, page, 0, seen)
            async for fresh in sub:
                yield fresh

    @staticmethod
    def stub(p: dict[str, Any], board: str, company: str) -> JobStub:
        host, _, _, public = _board(board)
        url = f"https://{host}/{public}{p['externalPath']}"
        return JobStub(
            source="workday",
            url=url,
            title=p["title"],
            company=company,
            location=p.get("locationsText") or "",
            posted_at=parse_posted(p.get("postedOn")),
            ats="workday",
            apply_url=url,
            remote=remote_from_text(p.get("locationsText"), p["title"]),
            extra={
                "board": board,
                "external_path": p["externalPath"],
                "req_id": (p.get("bulletFields") or [""])[0],
            },
        )

    async def fetch_details(self, http: Http, stub: JobStub) -> JobStub:
        # Only `discovered` jobs reach here: store_page drops stored duplicates before enrich.
        if m := _URL.search(stub.url):
            tenant, wd, site, path = m.groups()
            host = f"{tenant}.{wd}.myworkdayjobs.com"
        elif m := _SHARED_URL.search(stub.url):
            host, tenant, site, path = m.groups()
        else:
            return stub
        j = (await _send(http, "GET", f"https://{host}/wday/cxs/{tenant}/{site}{path}")).json()
        info = j.get("jobPostingInfo") or {}
        return stub.model_copy(
            update={
                "description": html_to_text(info.get("jobDescription") or ""),
                "apply_url": info.get("externalUrl") or stub.apply_url,
            }
        )
